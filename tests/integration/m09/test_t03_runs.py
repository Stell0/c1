"""M09-T03: a test definition is not a run; another target's run is not verification."""

from __future__ import annotations

from scripts import software_producer as sp
from tests.integration.m09.conftest import ledger_symbol, package, target, unit_for, units
from tests.integration.software import Software


def test_t03_definition_versus_execution(software: Software) -> None:
    async def run() -> None:
        case = software.case
        value = await package(case, "carol", ledger_symbol(), target("a1", "b1"))
        ledger_case = sp.test_case_id("ledger-create")
        test = unit_for(value, "tests", path="tests/test_api.py")
        assert test["test_case"]["id"] == ledger_case
        assert test["status"] == "definition-only" and test["matching_results"] == []
        runs = {
            unit["run_id"]: unit
            for unit in units(value, "runs")
            if unit["test_case"] == ledger_case
        }
        on_a2 = runs[sp.ident("test-run/unit-a2", "test-run")]
        assert on_a2["match"] == "other-target" and on_a2["result"] == "pass"
        assert [item["id"] for item in on_a2["snapshots"]] == [sp.snapshot_id("a2")]
        other_configuration = runs[sp.ident("test-run/unit-a1-py312", "test-run")]
        assert other_configuration["match"] == "other-target"
        assert other_configuration["configuration"]["name"] == "py312"
        assert [item["id"] for item in other_configuration["snapshots"]] == [sp.snapshot_id("a1")]
        assert all(unit["match"] != "matching" for unit in runs.values())
        assert "definition\\-only" in value["markdown"]

        # The same run matches, and verifies, only at its own target.
        fixed = await package(case, "carol", ledger_symbol(), target("a2", "b2"))
        test = unit_for(fixed, "tests", path="tests/test_api.py")
        assert test["status"] == "matching-run" and test["matching_results"] == ["pass"]
        py312 = await package(
            case, "carol", ledger_symbol(), target("a1", "b1", configuration="py312")
        )
        test = unit_for(py312, "tests", path="tests/test_api.py")
        assert test["status"] == "matching-run" and test["matching_results"] == ["pass"]

    software.run(run())
