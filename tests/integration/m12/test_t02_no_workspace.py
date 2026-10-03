"""M12-T02: no workspace step; a project filter narrows without changing IDs or access."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote, urlencode

import pytest

from tests.browser.harness import Person, browser, browser_enabled, explorer_server, sign_in
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m04.conftest import action, new_changeset
from tests.integration.m07.conftest import install_batteries, request_body
from tests.integration.m12.conftest import PERSON, directory_case, resource

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

PROJECT = "urn:c1:instance:dev:project/papertrader-view"
COMPANY_B = "urn:c1:instance:dev:entity/00000012-0000-4000-8000-000000000000"
C1 = "urn:c1:ns:core#"


async def _tag(case: LiveCase, identifiers: list[str]) -> None:
    """Add the project reference through an ordinary reviewed ChangeSet (M05-T07 precedent)."""
    operations = []
    for identifier in identifiers:
        record = await resource(case, identifier, "erin")
        properties = dict(record["properties"])
        properties[C1 + "projectReference"] = [PROJECT]
        record["properties"] = properties
        operations.append(
            {"kind": "replace", "resource_id": identifier, "record": record, "reason": "View"}
        )
    proposal = await new_changeset(case, operations, actor="erin")
    state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
    if state == "submitted":
        await action(case, proposal["id"], "validate", actor="erin")
    assert (await action(case, proposal["id"], "approve", actor="carol"))["state"] == "approved"
    assert (await action(case, proposal["id"], "apply", actor="carol"))["state"] == "applied"


async def _listed(person: Person, **params: str) -> list[str]:
    await person.goto("/explorer/entities" + ("?" + urlencode(params) if params else ""))
    rows = person.page.locator("tr[data-entity]")
    return [str(await rows.nth(i).get_attribute("data-entity")) for i in range(await rows.count())]


async def _api_ids(case: LiveCase, actor: str, **params: str) -> list[str]:
    response = await case.request("GET", "/v1/entities", actor=actor, params=params or None)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


async def _no_project_step(person: Person) -> None:
    """The start page and entity list need no workspace or project selection."""
    response = await person.goto("/explorer/")
    assert response is not None and response.status == 200
    assert person.page.url.endswith("/explorer/")
    # No selection control of any kind stands between sign-in and the data.
    assert await person.page.locator("main select, main input, main form").count() == 0
    await person.page.get_by_role("link", name="Entities").click()
    await person.page.wait_for_load_state("load")
    assert person.page.url.endswith("/explorer/entities")
    assert await person.page.locator("tr[data-entity]").count() > 0


def test_t02_directory_and_cross_project_context_without_workspace() -> None:
    async def run() -> None:
        async with directory_case() as (case, _scopes):
            await _tag(case, [PERSON, COMPANY_B])
            async with explorer_server(case), browser() as instance:
                carol = await sign_in(instance, "carol")
                alice = await sign_in(instance, "alice")
                await _no_project_step(carol)
                for person in (carol, alice):
                    unfiltered = await _listed(person)
                    filtered = await _listed(person, project_ref=PROJECT)
                    assert unfiltered == await _api_ids(case, person.name)
                    assert filtered == await _api_ids(case, person.name, project_ref=PROJECT)
                    # The filter narrows; it never adds a record or changes an ID.
                    assert set(filtered) <= set(unfiltered)
                    assert set(filtered) < set(unfiltered)
                    assert PERSON in filtered
                # Alice cannot read Company B; the filter it shares does not reveal it.
                assert COMPANY_B not in await _listed(alice)
                assert COMPANY_B not in await _listed(alice, project_ref=PROJECT)
                assert COMPANY_B in await _listed(carol, project_ref=PROJECT)
                # The same canonical Person page for both, with or without the filter.
                for person in (carol, alice):
                    await person.goto("/explorer/resource?id=" + quote(PERSON, safe=""))
                    assert await person.field("record-id") == PERSON
                hidden = await alice.goto("/explorer/resource?id=" + quote(COMPANY_B, safe=""))
                assert hidden is not None and hidden.status == 404

        async with live_case() as case:
            loaded: dict[str, Any] = await install_batteries(case)
            body = request_body(loaded)
            expected = await case.request("POST", "/v1/context", actor="dave", json=body)
            assert expected.status_code == 200, expected.text
            async with explorer_server(case), browser() as instance:
                dave = await sign_in(instance, "dave")
                await _no_project_step(dave)
                query = urlencode(
                    {
                        "profile": "graph-context@1",
                        "anchor_label": "Tesla",
                        "topics": "batteries",
                        "revision": loaded["revision"],
                    }
                )
                await dave.goto("/explorer/context?" + query)
                assert await dave.field("outcome") == "resolved"
                assert await dave.field("revision") == expected.json()["revision"]
                structured = expected.json()["structured"]
                anchor = structured["interpretation"]["anchor"]
                anchor_id = anchor["id"] if isinstance(anchor, dict) else anchor
                assert anchor_id in await dave.page.inner_text('[data-region="structured"]')

    asyncio.run(run())
