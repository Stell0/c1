"""M11-T06: quarantined drafts, lineage-aware widening, approval freshness."""

from __future__ import annotations

import asyncio

from tests.integration.m11.conftest import (
    accept,
    draft_operations,
    fixture_check,
    operation_step,
    propose,
    rescope,
    run_rule,
)
from tests.integration.software import Template, copy_of


def test_t06_audience_and_freshness(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            bob = (await case.principal("bob")).id
            check = fixture_check(software_template)

            # Creation outside a drafting scope fails even with creation rights.
            for role in ("creator", "contributor"):
                await case.grant("sw-shared", "bob", role)
            operations, _ = draft_operations(
                software_template, bob, key="outside", check=check, scope="sw-shared"
            )
            status, view = await propose(case, "bob", operations)
            assert status == 200 and view.get("codes") == ["C1-CS-051"], view

            operations, ids = draft_operations(software_template, bob, check=check)
            status, view = await propose(case, "bob", operations)
            assert status == 200, view
            await accept(case, view, "dave")

            # Widening needs the destination admin and every lineage scope's admin.
            proposal = await rescope(case, ids["document"], "sw-docs", "carol")
            assert proposal["state"] == "proposed"
            frank = await operation_step(case, proposal["id"], "approve", "frank")
            assert frank.status_code == 200 and frank.json()["state"] == "proposed", frank.text
            early = await operation_step(case, proposal["id"], "apply", "carol")
            assert early.status_code == 409, early.text
            own = await operation_step(case, proposal["id"], "approve", "carol")
            assert own.status_code == 403, own.text
            alice = await operation_step(case, proposal["id"], "approve", "alice")
            assert alice.status_code == 403, alice.text
            erin = await operation_step(case, proposal["id"], "approve", "erin")
            assert erin.status_code == 200 and erin.json()["state"] == "approved", erin.text
            applied = await operation_step(case, proposal["id"], "apply", "carol")
            assert applied.status_code == 200, applied.text
            read = await case.request(
                "GET", "/v1/documents/by-id", params={"document_id": ids["document"]}, actor="alice"
            )
            assert read.status_code == 200, read.text

            # Approval needs the latest rule check for exactly the draft's target.
            moved, ids = draft_operations(
                software_template,
                bob,
                key="moved",
                snapshots=("a2", "b1"),
                check=check,
                state="approved",
            )
            status, view = await propose(case, "bob", moved)
            assert status == 200 and view.get("codes") == ["C1-CS-050"], view
            fresh = await run_rule(
                case, software_template, ["a2", "b1"], "a2", "2026-03-03T09:00:00Z"
            )
            moved, _ = draft_operations(
                software_template,
                bob,
                key="moved",
                snapshots=("a2", "b1"),
                check=fresh,
                state="approved",
            )
            status, view = await propose(case, "bob", moved)
            assert status == 200 and view["state"] == "validated", view
            # A newer run for the same target supersedes the named check.
            await run_rule(case, software_template, ["a2", "b1"], "a2", "2026-03-04T09:00:00Z")
            stale, _ = draft_operations(
                software_template,
                bob,
                key="stale",
                snapshots=("a2", "b1"),
                check=fresh,
                state="approved",
            )
            status, view = await propose(case, "bob", stale)
            assert status == 200 and view.get("codes") == ["C1-CS-050"], view

    asyncio.run(run())
