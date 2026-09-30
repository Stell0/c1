"""M09-T04: a mocked dependency is not integration evidence; a live run keeps its target."""

from __future__ import annotations

from scripts import software_producer as sp
from tests.integration.m09.conftest import package, shop_symbol, target, units
from tests.integration.software import Software


def test_t04_mock_versus_integration(software: Software) -> None:
    async def run() -> None:
        case = software.case
        value = await package(case, "carol", shop_symbol(), target("a1", "b1"))
        runs = {unit["run_id"]: unit for unit in units(value, "runs")}
        mocked = runs[sp.ident("test-run/mocked-b1", "test-run")]
        assert mocked["match"] == "matching" and mocked["integration_mode"] == "mocked"
        assert [item["label"] for item in mocked["mocked_products"]] == ["Ledger"]
        assert mocked["integration_evidence"] is False
        live = runs[sp.ident("test-run/live-a1b1", "test-run")]
        assert live["match"] == "matching" and live["integration_mode"] == "live"
        assert live["integration_evidence"] is True and live["result"] == "pass"
        assert sorted(item["id"] for item in live["snapshots"]) == sorted(
            [sp.snapshot_id("a1"), sp.snapshot_id("b1")]
        )
        assert [item["label"] for item in live["exercised"]] == ["createInvoice"]
        assert "not integration evidence" in value["markdown"]
        assert "integration evidence for the target" in value["markdown"]

        later = await package(case, "carol", shop_symbol(), target("a2", "b2"))
        runs = {unit["run_id"]: unit for unit in units(later, "runs")}
        live = runs[sp.ident("test-run/live-a1b1", "test-run")]
        assert live["match"] == "other-target" and live["integration_evidence"] is False
        mocked = runs[sp.ident("test-run/mocked-b2", "test-run")]
        assert mocked["match"] == "matching" and mocked["integration_evidence"] is False
        assert all(not unit["integration_evidence"] for unit in units(later, "runs")), (
            "no live run covers the {a2, b2} target"
        )

    software.run(run())
