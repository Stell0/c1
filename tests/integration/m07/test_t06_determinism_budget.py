"""M07-T06: deterministic packages preserve complete units across budget pages."""

from __future__ import annotations

from tests.integration.m07.conftest import (
    Batteries,
    canonical,
    package,
    request_body,
    two_unit_page,
)


def test_t06_determinism_and_whole_unit_budget(batteries: Batteries) -> None:
    async def run() -> None:
        case, loaded = batteries.case, batteries.loaded
        full = await package(case, loaded)
        repeated = await package(case, loaded)
        assert canonical(full, loaded["revision"]) == canonical(repeated, loaded["revision"])
        first = await two_unit_page(case, loaded)
        assert len(first["structured"]["facts"]) == 2
        assert first["bounds"]["truncated"]
        assert first["bounds"]["deferred_units"] == len(full["structured"]["facts"]) - 2
        assert first["bounds"]["rendered_bytes"] <= first["bounds"]["maximum"]
        expected = {unit["id"]: unit for unit in full["structured"]["facts"]}
        joined = []
        current = first
        while True:
            for unit in current["structured"]["facts"]:
                assert unit == expected[unit["id"]], (
                    "Budget split or changed a caveat/conflict unit"
                )
                joined.append(unit)
            cursor = current["bounds"]["next_cursor"]
            if cursor is None:
                break
            current = await package(case, loaded, cursor=cursor)
        assert joined == full["structured"]["facts"]
        insufficient = await case.request(
            "POST",
            "/v1/context",
            actor="dave",
            json=request_body(loaded, budget={"unit": "bytes", "maximum": 2048}),
        )
        assert insufficient.status_code == 422, insufficient.text
        assert insufficient.json()["code"] == "C1-CX-010"
        assert insufficient.json()["minimum_required"] > 2048

    batteries.runner.run(run())
