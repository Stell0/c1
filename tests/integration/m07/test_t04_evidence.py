"""M07-T04: disagreements, duplicate imports and incomplete measurements survive."""

from __future__ import annotations

from typing import Any

from tests.integration.m07.conftest import B, Batteries, package


def test_t04_evidence_integrity(batteries: Batteries) -> None:
    async def run() -> None:
        loaded = batteries.loaded
        ids = loaded["fixture"]["ids"]
        result = await package(batteries.case, loaded)
        units = result["structured"]["facts"]

        def quantity(node: str, predicate: str) -> dict[str, Any]:
            return next(
                unit
                for unit in units
                if unit["node_id"] == ids[node] and unit["predicate"] == B + predicate
            )

        megapack = quantity("m-b3", "capacity")
        assert {claim["value"]["lexical"] for claim in megapack["claims"]} == {"3.9", "3.6"}
        assert megapack["comparison"] == "disagreement"
        assert megapack["disagreement"]["declared_conflict"]
        assert megapack["sources"] == 2
        assert {
            citation["source_id"] for claim in megapack["claims"] for citation in claim["citations"]
        } == {ids["m-source-a"], ids["m-source-b"]}
        for claim in megapack["claims"]:
            assert claim["measurement_id"] in {
                ids["m-capacity-a-measurement"],
                ids["m-capacity-b-measurement"],
            }
            qualifiers = {
                value["predicate"]: value["value"]["lexical"] for value in claim["qualifiers"]
            }
            assert qualifiers[B + "unit"] == "MWh"
            assert qualifiers[B + "conditions"] == "25 C; nominal discharge"
            assert claim["valid_time"]["start"]["state"] == "known"
        optimus = quantity("o-b1", "capacity")
        assert optimus["sources"] == 1 and optimus["imports"] == 2
        assert {
            activity
            for claim in optimus["claims"]
            for citation in claim["citations"]
            for activity in citation["imported_by"]
        } == {ids["o-capacity-import-1"], ids["o-capacity-import-2"]}
        assert all(
            citation["corroboration"] == "duplicate_import"
            for claim in optimus["claims"]
            for citation in claim["citations"]
        )
        density = quantity("v-b2", "energyDensity")
        assert density["claims"][0]["incomplete"] == ["unit"]
        for unit in units:
            assert unit["node_id"] in {ids["o-b1"], ids["v-b2"], ids["m-b3"]}
            assert unit["roles"]["version"][0]["id"] == unit["node_id"]
            assert len(unit["roles"]["product"]) == 1
        assert quantity("v-b2", "capacity")["claims"][0]["value"]["lexical"] == "75"

    batteries.runner.run(run())
