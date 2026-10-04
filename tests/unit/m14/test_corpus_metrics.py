"""M14 unit checks: deterministic corpus, independent gold, valid records, metric vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import corpus, metrics
from c1.interchange.jsonld import validate_records
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry

ROOT = Path(__file__).resolve().parents[3]


def test_generation_is_deterministic_and_scaled() -> None:
    first, second = corpus.generate(1), corpus.generate(1)
    assert json.dumps(first.records, sort_keys=True) == json.dumps(second.records, sort_keys=True)
    assert first.queries == second.queries
    assert first.manifest() == second.manifest()
    larger = corpus.generate(3)
    assert len(larger.records) > 2.5 * len(first.records)
    for scale in (first, larger):
        # The tested principal stays below the 5,000-candidate query ceiling.
        assert scale.manifest()["visible_to_tested_principal"] < 4500
        assert len({r["id"] for r in scale.records}) == len(scale.records)


def test_records_validate_against_the_installed_profiles() -> None:
    registry = ProfileRegistry()
    for name in ("directory", "topics", "batteries"):
        registry.load(ROOT / "profiles/available" / name)
    generated = corpus.generate(1)
    validate_records((NodeRecord.model_validate(r) for r in generated.records), registry)


def test_gold_is_restricted_to_visible_resources_and_never_empty_for_core_needs() -> None:
    generated = corpus.generate(1)
    for query in generated.queries:
        for identifier in query["gold"]:
            assert generated.visible(identifier), query["id"]
    families = {q["family"] for q in generated.queries}
    assert families == {
        "keyword",
        "alias",
        "label-prefix",
        "valid-at",
        "graph",
        "document",
        "context",
    }
    graph = [q for q in generated.queries if q["family"] == "graph"]
    assert all(q["gold"] and q["gold_paths"] for q in graph)
    # Graph-relevant versions carry no keyword: keyword-only retrieval cannot find them.
    keyworded = set(generated.keyword_index.get("battery", []))
    assert not keyworded & set(graph[0]["gold"])


@pytest.mark.parametrize(
    ("ranked", "gold", "k", "recall", "precision"),
    [
        (["a", "b", "c"], {"a", "c"}, 2, 0.5, 0.5),
        (["a", "b", "c"], {"a", "c"}, 3, 1.0, 2 / 3),
        ([], set(), 5, 1.0, 1.0),
        ([], {"a"}, 5, 0.0, 0.0),
    ],
)
def test_recall_and_precision(
    ranked: list[str], gold: set[str], k: int, recall: float, precision: float
) -> None:
    assert metrics.recall_at(ranked, gold, k) == pytest.approx(recall)
    assert metrics.precision_at(ranked, gold, k) == pytest.approx(precision)


def test_ndcg_mrr_paths_and_coverage() -> None:
    assert metrics.ndcg_at(["x", "a"], {"a"}, 2) == pytest.approx(1 / 1.5849625007211562)
    assert metrics.ndcg_at(["a", "x"], {"a"}, 2) == pytest.approx(1.0)
    assert metrics.reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert metrics.path_recall([["c", "p"]], [["c", "p"], ["c", "q"]]) == 0.5
    assert metrics.coverage({"u1"}, {"u1", "u2"}) == 0.5
    summary = metrics.summarize(["a", "b"], ["a"], ks=(1,))
    assert summary == {"mrr": 1.0, "recall@1": 1.0, "precision@1": 1.0, "ndcg@1": 1.0}
    assert metrics.macro([{"m": 1.0}, {"m": 0.0}]) == {"m": 0.5}


def test_chunks_respect_the_changeset_limit_and_never_split_a_group() -> None:
    generated = corpus.generate(1)
    batches = generated.chunks(200)
    assert sum(len(b) for b in batches) == len(generated.records)
    assert all(len(b) <= 200 for b in batches)
    where = {r["id"]: n for n, batch in enumerate(batches) for r in batch}
    groups: dict[str, set[int]] = {}
    for identifier, group in generated.group_of.items():
        groups.setdefault(group, set()).add(where[identifier])
    assert groups and all(len(batches_of) == 1 for batches_of in groups.values())
