"""M08-T05: repeated imports are no-ops; a competing producer keeps its own claim."""

from __future__ import annotations

from typing import Any

from scripts import software_producer as sp
from tests.integration.m08.conftest import (
    CaseLoader,
    Software,
    lookup_all,
    producer,
    snapshot,
    symbol,
)

S = "urn:c1:ns:software#"


def test_t05_repeat_import_is_idempotent_and_competing_claims_coexist(software: Software) -> None:
    case = software.case

    async def run() -> None:
        planner: sp.Planner = software.loaded["planner"]
        target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
        before = await lookup_all(case, "carol", {"target": target})
        head = await case.knowledge.head()
        runs = {item.key: item for item in planner.runs()}
        loader = CaseLoader(case)
        for key in ("scip/a1", "openapi/a1", "calls/b1", "analyzer/b1"):
            outcome = await sp.apply_run(loader, runs[key])
            assert outcome["state"] == "skipped", outcome
        # Even without the coverage shortcut, already-applied batches are not re-sent.
        outcome = await sp.apply_run(loader, runs["scip/b1"], skip_complete=False)
        assert outcome == {"run": "scip/b1", "state": "applied", "records": 0}
        assert await case.knowledge.head() == head
        assert await lookup_all(case, "carol", {"target": target}) == before

        # The same call site: the indexer resolves `validate` through the SCIP
        # reference (shop's validate); the analyzer's name-only method picks
        # ledger's. Both remain, each attributed to its own producer and activity.
        relationships = [
            item
            for item in before
            if item["kind"] == "relationship" and item["predicate"] == S + "staticCall"
        ]
        by_subject: dict[str, list[dict[str, Any]]] = {}
        for item in relationships:
            by_subject.setdefault(item["subject"], []).append(item)
        contested = [
            items for items in by_subject.values() if len({item["object"] for item in items}) == 2
        ]
        assert len(contested) == 1
        claims = {item["attributed_to"]: item for item in contested[0]}
        assert set(claims) == {producer(software, "indexer"), producer(software, "analyzer")}
        assert claims[producer(software, "indexer")]["object"] == symbol(
            "shop", "`shop.client`/validate()."
        )
        assert claims[producer(software, "indexer")]["origin"] == "imported"
        assert claims[producer(software, "analyzer")]["object"] == symbol(
            "ledger", "`ledger.api`/validate()."
        )
        assert claims[producer(software, "analyzer")]["origin"] == "derived"
        assert (
            claims[producer(software, "indexer")]["generated_by"]
            != claims[producer(software, "analyzer")]["generated_by"]
        )

    software.run(run())
