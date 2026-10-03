"""M12-T07: after a grant or binding change the next browser fetch is reauthorized."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote, urlencode

import pytest

from scripts import software_producer as sp
from tests.browser.harness import (
    ORIGIN,
    Person,
    browser,
    browser_enabled,
    explorer_server,
    sign_in,
)
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m06.conftest import fixture_spec, install_scoped_document
from tests.integration.m11.conftest import operation_step, rescope, target, update
from tests.integration.m12.conftest import AuditTap
from tests.integration.software import Template, copy_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"
CLIENT = sp.file_id("b2", "shop/client.py")
CLIENT_TEXT = "pricing_internal.price(order)"


def _team_parts() -> dict[str, str]:
    """Part ID -> text of every revision-1 part bound to the team scope."""
    return {
        item["id"]: item["properties"][C1 + "text"][0]["lexical"]
        for item in fixture_spec()["revision1"]
        if item["scope"] == "doc-team" and C1 + "text" in item["properties"]
    }


async def _scope_named(case: LiveCase, word: str) -> str:
    response = await case.request("GET", "/v1/access-scopes", actor="erin")
    return str(next(s["id"] for s in response.json()["access_scopes"] if word in s["label"]))


async def _reload(person: Person, path: str) -> tuple[int, str]:
    response = await person.goto(path)
    assert response is not None
    return response.status, await response.text()


async def _truncating_budget(case: LiveCase, actor: str, body: dict[str, Any]) -> int:
    for budget in (6144, 8192, 12288, 16384, 24576, 32768, 49152):
        response = await case.request(
            "POST",
            "/v1/context",
            actor=actor,
            json={**body, "budget": {"unit": "bytes", "maximum": budget}},
        )
        if response.status_code == 200 and response.json()["bounds"]["truncated"]:
            return budget
    raise AssertionError("no budget produced a truncated first page")


def test_t07_revocation_and_rescope_reauthorize_the_next_fetch(
    software_template: Template,
) -> None:
    async def run() -> None:
        team = _team_parts()
        assert team
        async with live_case() as case:
            _fixture, _scopes, revision1, _revision2 = await install_scoped_document(case)
            tap = AuditTap(case)
            team_scope = await _scope_named(case, "team")
            bob_id = (await case.principal("bob")).id
            async with explorer_server(case), browser() as instance:
                bob = await sign_in(instance, "bob")
                part_id, part_text = next(iter(team.items()))
                saved = [
                    "/explorer/document?id=" + quote(DOCUMENT, safe=""),
                    "/explorer/document?" + urlencode({"id": DOCUMENT, "revision": revision1}),
                    "/explorer/resource?id=" + quote(part_id, safe=""),
                    "/explorer/document/source?" + urlencode({"id": DOCUMENT, "format": "text"}),
                ]
                for path in saved:
                    status, html = await _reload(bob, path)
                    assert status == 200 and part_text in html, path

                revoked = await case.request(
                    "DELETE",
                    f"/v1/access-scopes/{quote(team_scope, safe='')}/members/"
                    + quote(bob_id, safe=""),
                    actor="erin",
                    params={"role": "reader"},
                )
                assert revoked.status_code == 200, revoked.text

                mark = tap.mark()
                for path in saved:
                    status, html = await _reload(bob, path)
                    assert part_text not in html, path
                    for text in team.values():
                        assert text not in html, path
                # The part page answers exactly like an unknown resource.
                status, _ = await _reload(bob, saved[2])
                assert status == 404
                reads = [e for e in tap.since(mark) if e["principal"] == bob_id]
                assert len([e for e in reads if e["operation"] == "resource_read"]) >= 1
                assert len([e for e in reads if e["operation"].startswith("document")]) >= 3

                # Back to a page delivered before the revocation is refetched (no-store).
                await bob.goto("/explorer/")
                await bob.page.go_back()
                await bob.page.go_forward()
                await bob.page.go_back()
                assert part_text not in await bob.page.content()

                # Signing out ends the server session; the next page asks for sign-in.
                async with bob.page.expect_navigation():
                    await bob.page.get_by_role("button", name="Sign out").click()
                response = await bob.goto("/explorer/documents")
                assert not bob.page.url.startswith(ORIGIN + "/explorer/documents")
                assert response is not None
                assert "kc-login" in await bob.page.content() or "username" in (
                    await bob.page.content()
                )

        async with copy_of(software_template) as case:
            body = update(target("a2", "b2"))
            budget = await _truncating_budget(case, "dave", body)
            spec = body["target"]
            context = "/explorer/context?" + urlencode(
                {
                    "profile": "documentation-update@1",
                    "anchor_id": body["anchor"]["id"],
                    "snapshots": "\n".join(spec["snapshots"]),
                    "contracts": "\n".join(spec["contracts"]),
                    "configurations": "\n".join(spec["configurations"]),
                    "budget": str(budget),
                }
            )
            lookup = "/explorer/software?" + urlencode(
                {"snapshots": "\n".join([sp.snapshot_id("a2"), sp.snapshot_id("b2")])}
            )
            async with explorer_server(case), browser() as instance:
                dave = await sign_in(instance, "dave")
                await dave.goto(context)
                continuation = await dave.page.get_attribute('[data-field="continuation"]', "href")
                assert continuation
                status, html = await _reload(dave, lookup)
                assert status == 200 and CLIENT_TEXT in html, (status, html[-2500:])

                proposal = await rescope(case, CLIENT, "sw-restricted", "erin")
                await case.grant("sw-restricted", "frank", "access_admin")
                approved = await operation_step(case, proposal["id"], "approve", "frank")
                assert approved.status_code == 200, approved.text
                applied = await operation_step(case, proposal["id"], "apply", "erin")
                assert applied.status_code == 200, applied.text

                # The continuation is reauthorized: either its prefix changed and it must
                # restart, or the next page is built without the code Dave lost.
                status, html = await _reload(dave, continuation)
                assert status in {200, 409}, status
                if status == 409:
                    assert await dave.field("problem-code") == "C1-CX-011"
                assert CLIENT_TEXT not in html and CLIENT not in html
                status, html = await _reload(dave, lookup)
                assert status == 200 and CLIENT_TEXT not in html
                assert CLIENT not in html

    asyncio.run(run())
