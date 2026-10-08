"""M11-T04: a draft adds records with lineage and never alters earlier history."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m11.conftest import (
    INVOICING,
    accept,
    context,
    draft_operations,
    fixture_check,
    propose,
    target,
    units,
    update,
)
from tests.integration.software import Template, copy_of


def test_t04_draft_lineage(software_template: Template) -> None:
    invoicing = sp.file_id(*INVOICING)

    async def run() -> None:
        async with copy_of(software_template) as case:
            bob = (await case.principal("bob")).id
            history_path = "/v1/documents/" + quote(invoicing, safe="") + "/history"
            first = await case.request("GET", history_path, actor="dave")
            assert first.status_code == 200, first.text
            history = first.json()
            before = await context(case, "dave", update(target("a2", "b2")))

            operations, ids = draft_operations(
                software_template, bob, check=fixture_check(software_template)
            )
            status, view = await propose(case, "bob", operations)
            assert status == 200 and view["state"] == "validated", view
            await accept(case, view, "dave")

            after = await context(case, "dave", update(target("a2", "b2")))
            [draft] = units(after, "drafts", "draft")
            assert draft["draft_id"] == ids["draft"]
            assert draft["author"] == bob
            assert draft["revises"] == invoicing
            assert draft["draft_state"] == "draft"
            assert draft["publication_state"] == "not-published"
            assert draft["target_snapshots"] == sorted([sp.snapshot_id("a2"), sp.snapshot_id("b2")])
            derived = {
                source["source_part"] for part in draft["parts"] for source in part["derived_from"]
            }
            assert derived == set(ids["sources"]) and len(derived) == 3
            assert [part["part_id"] for part in draft["parts"]] == ids["parts"]

            # Old document, its history, review candidates and discrepancies are unchanged.
            # The response's `revision` is the knowledge head it was served at,
            # which the accepted draft advances; every history entry is unchanged.
            later = await case.request("GET", history_path, actor="dave")
            assert later.status_code == 200, later.text
            assert later.json()["revision"] != history["revision"]
            unchanged = {k: v for k, v in later.json().items() if k != "revision"}
            assert unchanged == {k: v for k, v in history.items() if k != "revision"}
            for name in ("document-structure", "changes"):
                assert units(after, name) == units(before, name)

    asyncio.run(run())
