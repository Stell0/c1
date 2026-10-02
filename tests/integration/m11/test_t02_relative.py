"""M11-T02: obsolescence is relative to target snapshots and to individual parts."""

from __future__ import annotations

import asyncio
from typing import Any

from scripts import software_producer as sp
from tests.integration.m11.conftest import (
    INVOICING,
    context,
    parts_of,
    run_rule,
    target,
    units,
    update,
)
from tests.integration.software import Template, copy_of


def _document(package: dict[str, Any], document: str) -> list[dict[str, Any]]:
    return [
        unit
        for unit in units(package, "document-structure", "document-part")
        if unit["document_id"] == document
    ]


def _stable(package: dict[str, Any]) -> tuple[str, str]:
    revision = package["revision"]
    return (
        repr(package["structured"]).replace(revision, "<revision>"),
        package["markdown"].replace(revision, "<revision>"),
    )


def test_t02_relative_obsolescence(software_template: Template) -> None:
    planner: sp.Planner = software_template.loaded["planner"]
    invoicing = sp.file_id(*INVOICING)
    sections = parts_of(planner, *INVOICING)

    async def run() -> None:
        async with copy_of(software_template) as case:
            old_target = target("a1", "b1", contract="a1")
            before = await context(case, "bob", update(old_target))
            a1 = sp.snapshot_id("a1")
            for unit in _document(before, invoicing):
                assert unit["applicability"][a1]["state"] == "applicable"
                assert unit["applicability"][a1]["decided_at"] == "document"

            package = await context(case, "bob", update(target("a2", "b2")))
            a2, b2 = sp.snapshot_id("a2"), sp.snapshot_id("b2")
            states = {
                unit["part_id"]: unit["applicability"][a2] for unit in _document(package, invoicing)
            }
            assert set(states) == set(sections)
            for part, value in states.items():
                if sections[part] == "Creating an invoice":
                    assert value["state"] == "needs-review" and value["decided_at"] == "part"
                    assert [record["basis"] for record in value["records"]] == ["rule"]
                else:
                    # No declaration or record for a2: unknown, never obsolete.
                    assert value == {"state": "unknown", "decided_at": None, "records": []}
            assert all(
                unit["applicability"][b2]["state"] == "unknown"
                for unit in _document(package, invoicing)
            )
            assert "obsolete" not in repr(package["structured"]).lower()
            # Applicable guidance for the target stays applicable.
            guide = sp.guide_id("guides/ledger-ops-1.1.md")
            assert {unit["applicability"][a2]["state"] for unit in _document(package, guide)} == {
                "applicable"
            }

            # A further rule run for the newer target leaves the a1/b1 package unchanged.
            await run_rule(case, software_template, ["a2", "b2"], "a2", "2026-03-02T09:00:00Z")
            after = await context(case, "bob", update(old_target))
            assert _stable(after) == _stable(before)

    asyncio.run(run())
