"""M09-T02: the package preserves a documented rule the implementation violates."""

from __future__ import annotations

import copy
from typing import Any

from c1.context.markdown import _safe
from tests.integration.m09.conftest import ledger_symbol, package, target, unit_for, units
from tests.integration.software import Software

RULE = "The amount must be greater than zero; zero is rejected with 422."


def _without_goal_labels(value: dict[str, Any]) -> dict[str, Any]:
    structured: dict[str, Any] = copy.deepcopy(value["structured"])
    structured["interpretation"].pop("goal")
    for key in ("goal_statement", "section_labels", "bounds"):
        structured.pop(key)
    return structured


def test_t02_discrepancy_is_preserved_not_canonized(software: Software) -> None:
    async def run() -> None:
        case = software.case
        conformance = await package(case, "carol", ledger_symbol(), target("a1", "b1"))
        characterization = await package(
            case, "carol", ledger_symbol(), target("a1", "b1"), "characterization"
        )

        # The normative text is verbatim; the implementation shows the defect.
        rule = next(unit for unit in units(conformance, "normative") if RULE in unit["text"])
        validate = next(
            unit
            for unit in units(conformance, "implementation")
            if unit["text"].startswith("def validate(")
        )
        assert "return amount >= 0" in validate["text"]
        discrepancy = unit_for(
            conformance, "discrepancies", kind="discrepancy", normative_part=rule["part_id"]
        )
        assert discrepancy["implementation_part"] == validate["part_id"]
        assert discrepancy["normative_part"] == rule["part_id"]
        assert discrepancy["role"] == "interpretive"
        quotes = {citation.get("quote") for citation in discrepancy["citations"]}
        assert {"return amount >= 0", RULE} <= quotes

        # Normative and implementation text are never merged or restated.
        for unit in units(conformance, "normative"):
            assert ">= 0" not in unit["text"]
        for unit in units(conformance, "implementation"):
            assert "zero is rejected" not in unit["text"]

        # The goal changes only labels: same units, gaps, sources, and target.
        assert _without_goal_labels(conformance) == _without_goal_labels(characterization)
        labels = conformance["structured"]["section_labels"]
        other = characterization["structured"]["section_labels"]
        assert {key for key in labels if labels[key] != other[key]} == {
            "normative",
            "implementation",
        }
        assert "only oracle source" in conformance["structured"]["goal_statement"]
        assert "characterized" in characterization["structured"]["goal_statement"]
        markdown = conformance["markdown"]
        for key in ("normative", "implementation"):
            markdown = markdown.replace(_safe(labels[key]), _safe(other[key]))
        markdown = markdown.replace(
            _safe(conformance["structured"]["goal_statement"]),
            _safe(characterization["structured"]["goal_statement"]),
        ).replace("- goal: conformance", "- goal: characterization")
        assert markdown.split("## Bounds")[0] == characterization["markdown"].split("## Bounds")[0]

    software.run(run())
