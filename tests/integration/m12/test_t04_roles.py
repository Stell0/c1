"""M12-T04: forged browser actions are decided by the API exactly as raw API requests are."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from urllib.parse import quote

import pytest

from tests.browser.harness import ORIGIN, Person, browser, browser_enabled, explorer_server, sign_in
from tests.integration.m03.conftest import LiveCase
from tests.integration.m04.conftest import action, changeset_path, new_changeset
from tests.integration.m12.conftest import PERSON, PHONE, AuditTap, directory_case, grant

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _manual_assertion(attributed_to: str) -> dict[str, Any]:
    def literal(text: str, datatype: str = XSD + "string") -> dict[str, str]:
        return {"lexical": text, "datatype": datatype}

    return {
        "id": f"urn:c1:instance:dev:assertion/{uuid.uuid4()}",
        "types": [C1 + "Assertion"],
        "properties": {
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject": [PERSON],
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate": [PHONE],
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [literal("+1 555 0199")],
            C1 + "origin": [literal("manual")],
            C1 + "reviewState": [literal("reported")],
            C1 + "lifecycle": [literal("active")],
            C1 + "manualStatement": [literal("true", XSD + "boolean")],
            "http://www.w3.org/ns/prov#wasAttributedTo": [attributed_to],
        },
    }


async def _validated(case: LiveCase, scope: str, author: str) -> str:
    principal = (await case.principal(author)).id
    proposal = await new_changeset(
        case,
        [{"kind": "create", "record": _manual_assertion(principal), "scope_id": scope}],
        actor=author,
    )
    state = (await action(case, proposal["id"], "submit", actor=author))["state"]
    if state == "submitted":
        state = (await action(case, proposal["id"], "validate", actor=author))["state"]
    assert state == "validated"
    return str(proposal["id"])


async def _csrf(person: Person) -> str:
    await person.goto("/explorer/")
    value = await person.page.locator('input[name="csrf"]').first.get_attribute("value")
    assert value
    return value


async def _forge(
    person: Person, path: str, form: dict[str, str | float | bool], **headers: str
) -> int:
    """A scripted post carrying the person's own session cookie and form token.

    It models a client that holds valid browser credentials and edits the
    request; only the C1 API may decide the outcome.
    """
    cookies = [
        f"{c['name']}={c['value']}"
        for c in await person.context.cookies()
        if c["name"] == "__Host-c1_session"
    ]
    response = await person.page.request.post(
        ORIGIN + path,
        form=form,
        headers={"Origin": ORIGIN, "Cookie": "; ".join(cookies), **headers},
        max_redirects=0,
    )
    return response.status


async def _state(case: LiveCase, changeset_id: str) -> str:
    """Read as the author, who can see every ChangeSet in this test."""
    response = await case.request("GET", changeset_path(changeset_id), actor="carol")
    assert response.status_code == 200, response.text
    return str(response.json()["state"])


async def _outcome(person: Person, created: bool) -> tuple[str, str]:
    """A ChangeSet state, or the API status shown on a problem page."""
    if await person.page.locator('[data-field="state"]').count():
        return ("created", await person.field("state"))
    return ("created" if created else "refused", await person.field("problem-status"))


def test_t04_roles_are_enforced_by_the_api_not_the_page() -> None:
    async def run() -> None:
        async with directory_case() as (case, scopes):
            company_a, selected = scopes["dir-company-a"], scopes["dir-selected"]
            await grant(case, company_a, "carol", "creator", "contributor")
            await grant(case, company_a, "dave", "reader", "reviewer")
            await grant(case, selected, "carol", "creator", "contributor")
            approved = await _validated(case, company_a, "carol")
            assert (await action(case, approved, "approve", actor="dave"))["state"] == "approved"
            own = await _validated(case, company_a, "carol")
            protected = await _validated(case, selected, "carol")
            tap = AuditTap(case)
            async with explorer_server(case), browser() as instance:
                alice = await sign_in(instance, "alice")
                bob = await sign_in(instance, "bob")
                carol = await sign_in(instance, "carol")
                frank = await sign_in(instance, "frank")
                alice_csrf, bob_csrf, carol_csrf = (
                    await _csrf(alice),
                    await _csrf(bob),
                    await _csrf(carol),
                )

                # A reader cannot apply an approved ChangeSet by forging the form.
                raw = await case.request(
                    "POST",
                    changeset_path(approved, "apply"),
                    actor="alice",
                    headers={"Idempotency-Key": uuid.uuid4().hex},
                )
                forged = await _forge(
                    alice,
                    "/explorer/changeset/action",
                    {
                        "csrf": alice_csrf,
                        "id": approved,
                        "action": "apply",
                        "idempotency_key": uuid.uuid4().hex,
                    },
                )
                assert raw.status_code in {403, 404} and forged == raw.status_code, (
                    raw.status_code,
                    forged,
                    raw.text,
                )
                assert await _state(case, approved) == "approved"

                # A ChangeSet over records Alice cannot read is the uniform 404, and
                # forging its approval is refused the same way.
                page = await alice.goto("/explorer/changeset?id=" + quote(protected, safe=""))
                raw_read = await case.request("GET", changeset_path(protected), actor="alice")
                assert page is not None and page.status == raw_read.status_code == 404
                assert "+1 555 0199" not in alice.recorder.everything()
                raw = await case.request(
                    "POST", changeset_path(protected, "approve"), actor="alice"
                )
                forged = await _forge(
                    alice,
                    "/explorer/changeset/action",
                    {"csrf": alice_csrf, "id": protected, "action": "approve"},
                )
                assert forged == raw.status_code and raw.status_code in {403, 404}
                assert await _state(case, protected) == "validated"

                # Independent review: the author cannot approve her own ChangeSet.
                raw = await case.request("POST", changeset_path(own, "approve"), actor="carol")
                forged = await _forge(
                    carol,
                    "/explorer/changeset/action",
                    {"csrf": carol_csrf, "id": own, "action": "approve"},
                )
                assert raw.status_code == 403 and forged == 403
                assert await _state(case, own) == "validated"

                # Scope administration needs access_admin on that scope.
                member = (await case.principal("dave")).id
                body = {"member": member, "role": "access_admin"}
                raw = await case.request(
                    "POST",
                    f"/v1/access-scopes/{quote(company_a, safe='')}/members",
                    actor="bob",
                    json=body,
                )
                forged = await _forge(
                    bob,
                    "/explorer/scopes/member",
                    {
                        "csrf": bob_csrf,
                        "scope": company_a,
                        "member": member,
                        "role": "access_admin",
                        "grant": "grant",
                    },
                )
                assert raw.status_code == 403 and forged == 403
                dave_roles = await case.request("GET", "/v1/access-scopes/mine", actor="dave")
                for item in dave_roles.json()["access_scopes"]:
                    assert "access_admin" not in item["roles"]

                # Schema administration: Bob's profile installation never applies,
                # through the browser or the API, and both paths answer the same.
                outcomes = []
                for path in ("browser", "api"):
                    if path == "browser":
                        await bob.goto("/explorer/changesets/new?form=profile")
                        await bob.page.select_option("#cs-profile", "example-vehicle")
                        async with bob.page.expect_navigation():
                            await bob.page.get_by_role(
                                "button", name="Create draft ChangeSet"
                            ).click()
                        created = "/explorer/changeset?id=" in bob.page.url
                        if created:
                            async with bob.page.expect_navigation():
                                await bob.page.click('[data-action="submit"]')
                        outcomes.append(await _outcome(bob, created))
                    else:
                        response = await case.request(
                            "POST",
                            "/v1/changesets",
                            actor="bob",
                            headers={"Idempotency-Key": uuid.uuid4().hex},
                            json={
                                "base_revision": await case.knowledge.head(),
                                "operations": [
                                    {"kind": "install_profile", "profile": "example-vehicle"}
                                ],
                            },
                        )
                        if response.status_code in {200, 201}:
                            submitted = await case.request(
                                "POST",
                                changeset_path(response.json()["id"], "submit"),
                                actor="bob",
                            )
                            outcomes.append(
                                (
                                    "created",
                                    str(submitted.json().get("state", submitted.status_code)),
                                )
                            )
                        else:
                            outcomes.append(("refused", str(response.status_code)))
                assert outcomes[0] == outcomes[1], outcomes
                assert outcomes[0] != ("created", "validated"), outcomes
                schema = await case.request("GET", "/v1/schema", actor="bob")
                assert "example-vehicle" not in [p["name"] for p in schema.json()["profiles"]]

                # The listings show nothing to a principal with no scope relation.
                mine = await case.request("GET", "/v1/access-scopes/mine", actor="frank")
                assert mine.json() == {"access_scopes": []}
                ops = await case.request("GET", "/v1/security-operations", actor="frank")
                assert ops.json() == {"security_operations": [], "truncated": False}
                await frank.goto("/explorer/scopes")
                assert await frank.page.locator("tr[data-scope]").count() == 0

                # Missing CSRF or a foreign origin is refused before any API call.
                mark = tap.mark()
                assert (
                    await _forge(
                        carol, "/explorer/changeset/action", {"id": own, "action": "withdraw"}
                    )
                    == 403
                )
                assert (
                    await _forge(
                        carol,
                        "/explorer/changeset/action",
                        {"csrf": carol_csrf, "id": own, "action": "withdraw"},
                        Origin="http://attacker.invalid",
                    )
                    == 403
                )
                assert (
                    await _forge(
                        carol,
                        "/explorer/changeset/action",
                        {"csrf": "wrong", "id": own, "action": "withdraw"},
                    )
                    == 403
                )
                assert not [e for e in tap.since(mark) if e["operation"].startswith("changeset")]
                assert await _state(case, own) == "validated"

    asyncio.run(run())
