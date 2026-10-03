"""M12-T01: a browser user and an API client make the same reviewed write."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from tests.browser.harness import Person, browser, browser_enabled, explorer_server, sign_in
from tests.integration.m03.conftest import LiveCase
from tests.integration.m04.conftest import action, new_changeset
from tests.integration.m12.conftest import (
    PERSON,
    PHONE,
    AuditTap,
    directory_case,
    grant,
    resource,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PHONE_VALUE = "+1 555 0100"
WRITE_ROUTES = ["changeset_create", "changeset_submit", "changeset_approve", "changeset_apply"]


async def _browser_write(carol: Person, dave: Person, scope: str) -> str:
    page = carol.page
    await carol.goto(f"/explorer/resource?id={PERSON}")
    await page.get_by_role("link", name="Add a source-backed assertion").click()
    await page.fill("#cs-predicate", PHONE)
    await page.select_option("#cs-object-kind", "literal")
    await page.fill("#cs-object", PHONE_VALUE)
    await page.select_option("#cs-origin", "manual")
    await page.fill("#cs-source-title", "Synthetic phone list")
    await page.fill("#cs-source-kind", "document")
    await page.fill("#cs-source-revision", "list-r1")
    await page.fill("#cs-excerpt", "Direct line: +1 555 0100")
    await page.select_option("#cs-scope", value=scope)
    async with page.expect_navigation():
        await page.get_by_role("button", name="Create draft ChangeSet").click()
    assert "/explorer/changeset?id=" in page.url, await page.content()
    assert await carol.field("state") == "draft"
    changeset_id = await carol.field("changeset-id")
    await page.click('[data-action="submit"]')
    await page.wait_for_load_state("load")
    assert await carol.field("state") == "validated"
    assert await carol.field("validation-status") == "accepted"

    await dave.goto(f"/explorer/changeset?id={changeset_id}")
    await dave.page.click('[data-action="approve"]')
    await dave.page.wait_for_load_state("load")
    assert await dave.field("state") == "approved"
    await dave.page.click('[data-action="apply"]')
    await dave.page.wait_for_load_state("load")
    assert await dave.field("state") == "applied"
    return changeset_id


async def _api_write(case: LiveCase, scope: str) -> str:
    base = "urn:c1:instance:dev:"
    source_id, evidence_id, assertion_id = (
        f"{base}source/{uuid.uuid4()}",
        f"{base}evidence/{uuid.uuid4()}",
        f"{base}assertion/{uuid.uuid4()}",
    )

    def literal(text: str, datatype: str = XSD + "string") -> dict[str, str]:
        return {"lexical": text, "datatype": datatype}

    records = [
        {
            "id": source_id,
            "types": [C1 + "Source"],
            "properties": {
                "http://purl.org/dc/terms/title": [literal("Synthetic phone list")],
                C1 + "sourceKind": [literal("document")],
                C1 + "sourceRevision": [literal("list-r1")],
            },
        },
        {
            "id": evidence_id,
            "types": [C1 + "Evidence"],
            "properties": {
                C1 + "assertionRef": [assertion_id],
                "http://www.w3.org/ns/oa#hasSource": [source_id],
                C1 + "sourceRevision": [literal("list-r1")],
                C1 + "excerpt": [literal("Direct line: +1 555 0100")],
            },
        },
        {
            "id": assertion_id,
            "types": [C1 + "Assertion"],
            "properties": {
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject": [PERSON],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate": [PHONE],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [literal(PHONE_VALUE)],
                C1 + "origin": [literal("manual")],
                C1 + "reviewState": [literal("reported")],
                C1 + "lifecycle": [literal("active")],
                C1 + "evidence": [evidence_id],
                C1 + "manualStatement": [literal("false", XSD + "boolean")],
            },
        },
    ]
    proposal = await new_changeset(
        case,
        [{"kind": "create", "record": r, "scope_id": scope} for r in records],
        actor="bob",
    )
    changeset_id = str(proposal["id"])
    state = (await action(case, changeset_id, "submit", actor="bob"))["state"]
    if state == "submitted":
        state = (await action(case, changeset_id, "validate", actor="bob"))["state"]
    assert state == "validated"
    assert (await action(case, changeset_id, "approve", actor="dave"))["state"] == "approved"
    assert (await action(case, changeset_id, "apply", actor="dave"))["state"] == "applied"
    return changeset_id


async def _committed(case: LiveCase, changeset_id: str) -> tuple[dict[str, Any], list[Any]]:
    response = await case.request("GET", f"/v1/changesets/{changeset_id}", actor="dave")
    assert response.status_code == 200, response.text
    changeset = response.json()
    records = [await resource(case, op["record"]["id"], "dave") for op in changeset["operations"]]
    return changeset, records


def _normalized(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace minted IDs with their role, so only content and structure are compared."""
    names = {}
    for record in records:
        kind = record["types"][0].rsplit("#", 1)[-1].lower()
        names[record["id"]] = "<" + kind + ">"

    def value(item: Any) -> Any:
        return names.get(item, item) if isinstance(item, str) else item

    return sorted(
        (
            {
                "id": names[r["id"]],
                "types": r["types"],
                "properties": {
                    k: sorted((value(v) for v in vs), key=str)
                    for k, vs in sorted(r["properties"].items())
                },
            }
            for r in records
        ),
        key=lambda r: r["id"],
    )


def test_t01_browser_and_api_client_produce_equivalent_attributed_records() -> None:
    async def run() -> None:
        async with directory_case() as (case, scopes):
            scope = scopes["dir-company-a"]
            await grant(case, scope, "carol", "creator", "contributor")
            await grant(case, scope, "bob", "creator", "contributor", "reader")
            await grant(case, scope, "dave", "reader", "reviewer")
            tap = AuditTap(case)
            carol_id = (await case.principal("carol")).id
            dave_id = (await case.principal("dave")).id
            bob_id = (await case.principal("bob")).id
            async with explorer_server(case), browser() as instance:
                carol = await sign_in(instance, "carol")
                dave = await sign_in(instance, "dave")
                mark = tap.mark()
                browser_changeset = await _browser_write(carol, dave, scope)
                browser_events = tap.since(mark)
            mark = tap.mark()
            api_changeset = await _api_write(case, scope)
            api_events = tap.since(mark)

            browser_cs, browser_records = await _committed(case, browser_changeset)
            api_cs, api_records = await _committed(case, api_changeset)
            assert _normalized(browser_records) == _normalized(api_records)
            # Attribution correctly differs; review and apply are by the same reviewer.
            assert browser_cs["author"] == carol_id
            assert api_cs["author"] == bob_id
            for record in browser_records + api_records:
                binding = await case.runtime.plane.bindings(record["id"])
                assert binding is not None and binding.scope_id == scope
            # The browser used the same API routes, as the same people, and no other write.
            for events, author in ((browser_events, carol_id), (api_events, bob_id)):
                writes = [
                    (e["principal"], e["operation"])
                    for e in events
                    if e["operation"].startswith("changeset_")
                    and e["operation"]
                    not in {"changeset_read", "changeset_list", "changeset_validation_read"}
                    and e["outcome"] == "allowed"
                ]
                assert writes == [
                    (author, "changeset_create"),
                    (author, "changeset_submit"),
                    (dave_id, "changeset_approve"),
                    (dave_id, "changeset_apply"),
                ], writes
                assert not any(
                    e["operation"].startswith(("probe", "security_", "scope_member"))
                    for e in events
                )

    asyncio.run(run())
