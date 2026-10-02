"""M11-T07: current bindings govern old packages, drafts and lineage after widening."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m03.conftest import LiveCase
from tests.integration.m11.conftest import (
    accept,
    context,
    draft_operations,
    fixture_check,
    head,
    operation_step,
    propose,
    rescope,
    target,
    units,
    update,
)
from tests.integration.software import Template, copy_of

CLIENT = sp.file_id("b2", "shop/client.py")


async def _widen(case: LiveCase, template: Template, *, lineage: bool) -> dict[str, Any]:
    bob = (await case.principal("bob")).id
    operations, ids = draft_operations(
        template, bob, check=fixture_check(template), lineage=lineage
    )
    status, view = await propose(case, "bob", operations)
    assert status == 200, view
    await accept(case, view, "dave")
    proposal = await rescope(case, ids["document"], "sw-docs", "carol")
    for approver in ("frank", "erin") if lineage else ("frank",):
        response = await operation_step(case, proposal["id"], "approve", approver)
        assert response.status_code == 200, response.text
    applied = await operation_step(case, proposal["id"], "apply", "carol")
    assert applied.status_code == 200, applied.text
    return ids


async def _alice_view(case: LiveCase, ids: dict[str, Any]) -> str:
    """Alice's document and part views, with the copy's own head normalized."""
    current = await head(case)
    views = []
    for path in (
        "/v1/documents/by-id?document_id=" + quote(ids["document"], safe=""),
        "/v1/documents/" + quote(ids["document"], safe="") + "/parts",
    ):
        response = await case.request("GET", path, actor="alice")
        assert response.status_code == 200, response.text
        views.append(response.json())
    return repr(views).replace(current, "<revision>")


def _mentions(package: dict[str, Any], identifier: str) -> bool:
    return identifier in repr(package["structured"]) or identifier in package["markdown"]


def test_t07_historical_protection(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case, copy_of(software_template) as plain:
            ids = await _widen(case, software_template, lineage=True)
            plain_ids = await _widen(plain, software_template, lineage=False)
            historical = await head(case)
            planner: sp.Planner = software_template.loaded["planner"]
            submit = planner._definition_part("b2", "shop", "`shop.client`/submit_order().")
            assert submit is not None
            before = await context(case, "dave", update(target("a2", "b2")))
            assert _mentions(before, CLIENT) and _mentions(before, submit)
            [draft] = units(before, "drafts", "draft")
            sources = {s["source_part"] for part in draft["parts"] for s in part["derived_from"]}
            assert submit in sources and len(sources) == 3

            # Move b2's client module to the restricted scope (current bindings).
            proposal = await rescope(case, CLIENT, "sw-restricted", "erin")
            await case.grant("sw-restricted", "frank", "access_admin")
            approved = await operation_step(case, proposal["id"], "approve", "frank")
            assert approved.status_code == 200, approved.text
            applied = await operation_step(case, proposal["id"], "apply", "erin")
            assert applied.status_code == 200, applied.text

            # Dave's historical package and the draft lineage lose that code.
            old = await context(case, "dave", update(target("a2", "b2"), revision=historical))
            assert not _mentions(old, CLIENT) and not _mentions(old, submit)
            assert "shop.client.submit_order" not in old["markdown"]
            [draft] = units(old, "drafts", "draft")
            remaining = {
                source["source_part"] for part in draft["parts"] for source in part["derived_from"]
            }
            assert remaining == sources - {submit}
            carol = await context(case, "carol", update(target("a2", "b2"), revision=historical))
            assert _mentions(carol, CLIENT) and _mentions(carol, submit)

            # Alice reads the widened draft text and nothing of its lineage sources.
            assert await _alice_view(case, ids) == await _alice_view(plain, plain_ids)
            for source in sources:
                hidden = await case.request(
                    "GET", "/v1/resources/" + quote(source, safe=""), actor="alice"
                )
                unknown = await case.request(
                    "GET",
                    "/v1/resources/" + quote(sp.ident("part/none", "part"), safe=""),
                    actor="alice",
                )
                assert hidden.status_code == unknown.status_code == 404
                assert hidden.json() == unknown.json()

    asyncio.run(run())
