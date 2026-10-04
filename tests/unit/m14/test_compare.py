"""M14 compare classification, canonicalization and configuration registry."""

from __future__ import annotations

import copy
from typing import Any

from benchmark.compare import baseline_subset, compare
from benchmark.configurations import CONFIGURATIONS
from benchmark.corpus import generate, twin
from benchmark.runner import Runner, canonical


def _result() -> dict[str, Any]:
    manifest = generate(1).manifest()
    return {
        "corpus": manifest,
        "c1_revision": "abc",
        "host": {"hostname": "makako", "cpu": [], "memory": "", "podman": "5"},
        "fidelity": {"score": 1.0, "passed": True},
        "quality": {"families": {"keyword/exact": {"recall@10": 1.0, "queries": 3}}},
        "security": {"score": 1.0, "passed": True},
        "revocation": {"passed": True},
        "performance": {"families": {"keyword/exact": {"median_ms": 100.0}}},
    }


def test_compare_against_itself_reports_no_change() -> None:
    result = _result()
    report = compare(baseline_subset({"S": result}), result)
    assert report["scale"] == "S"
    assert not report["hard_failures"] and not report["changes"]
    assert not report["performance_warnings"] and not report["notes"]


def test_hard_failures_quality_changes_and_slowdowns_are_classified() -> None:
    baseline = baseline_subset({"S": _result()})
    worse = copy.deepcopy(_result())
    worse["fidelity"] = {"score": 0.99, "passed": False}
    worse["security"] = {"score": 0.5, "passed": False}
    worse["revocation"] = {"passed": False}
    worse["quality"]["families"]["keyword/exact"]["recall@10"] = 0.5
    worse["performance"]["families"]["keyword/exact"]["median_ms"] = 151.0
    report = compare(baseline, worse)
    assert report["hard_failures"] == ["fidelity", "security", "revocation"]
    assert report["changes"] == [
        {
            "family": "keyword/exact",
            "metric": "recall@10",
            "baseline": 1.0,
            "current": 0.5,
            "direction": "lower",
        }
    ]
    assert report["performance_warnings"][0]["current_median_ms"] == 151.0
    other_host = copy.deepcopy(worse)
    other_host["host"]["hostname"] = "laptop"
    assert not compare(baseline, other_host)["performance_warnings"]


def test_canonical_removes_only_declared_volatility() -> None:
    page = {
        "revision": "commit-0123456789",
        "items": [{"id": "x", "label": "A"}],
        "markdown": "at commit-0123456789",
        "next_cursor": "c" * 20,
        "count": 1,
    }
    assert canonical(page) == {
        "items": [{"id": "x", "label": "A"}],
        "markdown": "at <volatile>",
        "count": 1,
    }
    assert canonical({**page, "count": 2}) != canonical(page)


def test_only_the_deterministic_configuration_is_available() -> None:
    assert [n for n, c in CONFIGURATIONS.items() if c["available"]] == ["deterministic"]
    reported = Runner.ablations()
    assert reported["deterministic"] == {"status": "RUN"}
    assert all(
        v["status"] == "NOT_AVAILABLE" and v["reason"]
        for k, v in reported.items()
        if k != "deterministic"
    )


def test_twin_resources_are_new_identities_and_revisions_keep_them() -> None:
    corpus = generate(1)
    first, second = twin(corpus), twin(corpus, generation=2)
    ids = {r["id"] for r in first}
    assert not ids & set(corpus.scope_of)
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert any(a != b for a, b in zip(first, second, strict=True))
