"""M10-T06: no sufficiency judgement, free text, or implicit fallback."""

from __future__ import annotations

from tests.integration.m10.conftest import context, documentation, implementation, target
from tests.integration.software import Software


def test_t06_no_sufficiency_oracle(software: Software) -> None:
    async def run() -> None:
        case = software.case
        free_text = {**documentation(target("a1", "b1")), "question": "Why does it time out?"}
        await context(case, "carol", free_text, status=400)
        goal = {**documentation(target("a1", "b1")), "goal": "conformance"}
        await context(case, "carol", goal, status=400)
        await context(case, "carol", implementation(target("a1", "b1"), []), status=400)

        value = await context(
            case, "carol", documentation(target("a1", "b1"), ["timeout", "nonexistent aspect"])
        )
        report = {
            item["requested"]: item["outcome"]
            for item in value["structured"]["interpretation"]["aspects"]
        }
        assert report == {"timeout": "resolved", "nonexistent aspect": "unresolved"}
        assert [item["aspect"]["label"] for item in value["structured"]["missing_aspects"]] == [
            "Timeout"
        ]
        # The documentation stage returns a follow-up but never runs the second stage.
        assert "implementation" not in value["structured"]["sections"]
        assert set(value["followup"]) == {"revision", "target", "missing_aspects", "token"}

    software.run(run())
