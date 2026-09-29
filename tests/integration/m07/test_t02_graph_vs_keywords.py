"""M07-T02: bounded paths and declared topics differ from exact keywords."""

from __future__ import annotations

from tests.integration.m07.conftest import Batteries, assert_golden, package, serialized


def test_t02_graph_relevance_is_not_keyword_propagation(batteries: Batteries) -> None:
    async def run() -> None:
        case, loaded = batteries.case, batteries.loaded
        ids = loaded["fixture"]["ids"]
        result = await package(case, loaded)
        material = result["structured"]
        assert ids["m-b3"] in {unit["node_id"] for unit in material["facts"]}
        assert any(
            path["node_ids"] == [ids["tesla"], ids["megapack"], ids["m-b3"]]
            for path in material["orientation"]
        )
        found = await case.request(
            "GET", "/v1/entities", actor="dave", params={"keywords_all": "batteries,tesla"}
        )
        assert found.status_code == 200, found.text
        keyword_ids = [item["id"] for item in found.json()["items"]]
        assert keyword_ids == [ids["v-b2"]]
        assert_golden("keywords-all.json", keyword_ids, loaded["revision"])
        for unrelated in ("solar", "instrument"):
            assert ids[unrelated] not in serialized(material)
        storage = await package(case, loaded, topics=["storage"])
        energy = await package(case, loaded, topics=["energy storage"])
        assert (
            storage["structured"]["interpretation"]["topics"]
            == energy["structured"]["interpretation"]["topics"]
        )
        assert storage["structured"]["facts"] == energy["structured"]["facts"]

    batteries.runner.run(run())
