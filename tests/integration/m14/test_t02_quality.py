"""M14-T02: every metric family is reported; exact-semantics families have recall 1."""

from typing import Any

FAMILIES = {
    "keyword/exact",
    "alias/exact",
    "label-prefix/exact",
    "valid-at/exact",
    "document/exact",
    "graph/keyword-only",
    "graph/neighborhood",
    "graph/graph-context",
    "context/graph-context",
}
METRICS = {"mrr"} | {f"{m}@{k}" for m in ("recall", "precision", "ndcg") for k in (5, 10, 50)}


def test_t02_retrieval_quality_is_reported_per_family(results: dict[str, dict[str, Any]]) -> None:
    for name, result in results.items():
        quality = result["quality"]
        assert set(quality["families"]) == FAMILIES, name
        for family, row in quality["families"].items():
            assert METRICS <= set(row), (name, family)
        assert "path_recall" in quality["families"]["graph/graph-context"], name
        context = quality["families"]["context/graph-context"]
        assert {"coverage_first_page", "coverage_all_pages", "pages_to_full_coverage"} <= set(
            context
        )
        budgets = {
            key.split("/")[-1].split("#")[0]
            for key in quality["per_query"]
            if key.startswith("context/")
        }
        assert budgets == {"8192", "32768", "65536"}, name
        # Exact keyword, alias, valid-time and document semantics are correctness checks.
        assert not quality["exact_semantics_failures"], (name, quality["exact_semantics_failures"])
        # Recall@K cannot reach 1 when a need has more than K relevant items; the
        # set equality above is the exact check, and here every need whose gold
        # set fits in K must be complete at K.
        for key, row in quality["per_query"].items():
            family = key.split("/")[0]
            if family in {"kw-any", "kw-all", "alias", "valid-at", "doc"} and row["gold"] <= 50:
                assert row["recall@50"] == 1.0, (name, key)
