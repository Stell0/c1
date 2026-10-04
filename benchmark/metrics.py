"""Retrieval metrics with binary relevance (M14 D5). Pure functions."""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at(ranked: Sequence[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0 if not ranked[:k] else 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def precision_at(ranked: Sequence[str], gold: set[str], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 1.0 if not gold else 0.0
    return len(set(top) & gold) / len(top)


def ndcg_at(ranked: Sequence[str], gold: set[str], k: int) -> float:
    gains = [1.0 if item in gold else 0.0 for item in ranked[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    if ideal == 0:
        return 1.0 if dcg == 0 else 0.0
    return dcg / ideal


def reciprocal_rank(ranked: Sequence[str], gold: set[str]) -> float:
    if not gold:
        return 1.0 if not ranked else 0.0
    for index, item in enumerate(ranked):
        if item in gold:
            return 1.0 / (index + 1)
    return 0.0


def path_recall(found: Sequence[Sequence[str]], gold: Sequence[Sequence[str]]) -> float:
    if not gold:
        return 1.0
    present = {tuple(path) for path in found}
    return sum(1 for path in gold if tuple(path) in present) / len(gold)


def coverage(found: set[str], required: set[str]) -> float:
    if not required:
        return 1.0
    return len(found & required) / len(required)


def summarize(
    ranked: Sequence[str], gold: Sequence[str], ks: Sequence[int] = (5, 10, 50)
) -> dict[str, float]:
    gold_set = set(gold)
    result: dict[str, float] = {"mrr": reciprocal_rank(ranked, gold_set)}
    for k in ks:
        result[f"recall@{k}"] = recall_at(ranked, gold_set, k)
        result[f"precision@{k}"] = precision_at(ranked, gold_set, k)
        result[f"ndcg@{k}"] = ndcg_at(ranked, gold_set, k)
    return result


def macro(rows: Sequence[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = sorted({k for row in rows for k in row})
    return {k: round(sum(row.get(k, 0.0) for row in rows) / len(rows), 6) for k in keys}
