"""Explain matched filters using only the authorized selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def explain_matches(
    matched_filters: Mapping[str, Iterable[str]], authorized_ids: Iterable[str]
) -> tuple[dict[str, object], ...]:
    """Return stable explanations only for IDs present in the selected result.

    Filter evaluation must already have run over fully authorized records. A
    hidden or unselected ID in ``matched_filters`` is never represented here.
    """
    selected = set(authorized_ids)
    return tuple(
        {"id": record_id, "matched_filters": sorted(set(matched_filters.get(record_id, ())))}
        for record_id in sorted(selected)
    )
