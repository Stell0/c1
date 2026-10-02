"""M10-T01: applicable guidance outranks newer guides for other targets."""

from __future__ import annotations

from tests.integration.m10.conftest import context, documentation, section, target, titles
from tests.integration.software import Software


def test_t01_applicability_before_age(software: Software) -> None:
    async def run() -> None:
        case = software.case
        early = await context(case, "carol", documentation(target("a1", "b1")))
        guidance = section(early, "guidance")
        assert titles(guidance)[0] == "Ledger operations guide 1.0"
        assert "Ledger operations guide 1.1" not in titles(guidance)
        assert all(unit["label"] == "official guidance" for unit in guidance)
        others = section(early, "other-target-documentation")
        assert {unit["document"]["title"] for unit in others} >= {"Ledger operations guide 1.1"}
        assert all("text" not in unit and unit["citations"] == [] for unit in others)
        assert "customer_id" not in early["markdown"]  # no text from the 1.1 guide

        later = await context(case, "carol", documentation(target("a2", "b2")))
        guidance = section(later, "guidance")
        assert titles(guidance)[0] == "Ledger operations guide 1.1"
        assert "Shop integration troubleshooting" not in titles(guidance)
        warnings = [u for u in section(later, "warnings") if u["kind"] == "applicability-warning"]
        assert [w["document"]["title"] for w in warnings] == ["Shop integration troubleshooting"]
        assert any(
            "does not apply to Shop 2.1" in (c.get("excerpt") or "") or c.get("part_id")
            for c in warnings[0]["citations"]
        )

    software.run(run())
