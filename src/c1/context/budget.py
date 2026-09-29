"""Whole-unit selection measured against the complete rendered Markdown bytes."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from c1.context.errors import ContextError
from c1.context.markdown import render_markdown
from c1.context.structured import public_value, render_structured, unit_citations


def prepare_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Number citations over the full selection before pagination, without mutation."""
    prepared = public_value(units)
    numbers: dict[str, int] = {}
    for unit in prepared:
        for citation in unit_citations(unit):
            identifier = citation.get("id", citation["evidence_id"])
            citation["id"] = identifier
            citation["n"] = numbers.setdefault(identifier, len(numbers) + 1)
    return prepared  # type: ignore[no-any-return]


def _render_page(
    base: dict[str, Any],
    units: list[dict[str, Any]],
    *,
    offset: int,
    count: int,
    maximum: int,
    cursor: str | None,
    deadline: float | None,
) -> dict[str, Any]:
    deferred = len(units) - offset - count
    bounds: dict[str, Any] = {
        "truncated": deferred > 0,
        "deferred_units": deferred,
        "next_cursor": cursor,
        "unit": "bytes",
        "maximum": maximum,
        "rendered_bytes": 0,
        "offset": offset,
        "included_units": count,
    }
    _check_deadline(deadline)
    structured = render_structured(base, units[offset : offset + count], bounds)
    structured["bounds"] = bounds
    # Only the decimal byte count is self-referential; its digit count stabilizes.
    for _ in range(16):
        _check_deadline(deadline)
        markdown = render_markdown(structured)
        _check_deadline(deadline)
        measured = len(markdown.encode("utf-8"))
        if measured == bounds["rendered_bytes"]:
            return {"markdown": markdown, "structured": structured, "bounds": bounds}
        bounds["rendered_bytes"] = measured
    raise RuntimeError("context byte-count fixed point did not converge")


def build_page(
    base: dict[str, Any],
    units: list[dict[str, Any]],
    *,
    offset: int = 0,
    maximum: int = 65536,
    cursor_for_offset: Callable[[int], str | None],
    deadline: float | None = None,
) -> dict[str, Any]:
    """Choose the longest fitting contiguous prefix, never emit a zero-progress page."""
    if not 0 <= offset <= len(units):
        raise ValueError("invalid context unit offset")
    if maximum < 1:
        raise ValueError("maximum must be positive")
    _check_deadline(deadline)
    remaining = len(units) - offset
    fixed = _render_page(
        base, units, offset=offset, count=0, maximum=maximum, cursor=None, deadline=deadline
    )
    if not remaining:
        if fixed["bounds"]["rendered_bytes"] > maximum:
            minimum = _minimum_required(
                base,
                units,
                offset=offset,
                count=0,
                cursor=None,
                deadline=deadline,
                initial=fixed["bounds"]["rendered_bytes"],
            )
            raise ContextError(
                422,
                "C1-CX-010",
                "insufficient_budget",
                details={
                    "minimum_required": minimum,
                },
            )
        return fixed
    complete = _render_page(
        base,
        units,
        offset=offset,
        count=remaining,
        maximum=maximum,
        cursor=None,
        deadline=deadline,
    )
    if complete["bounds"]["rendered_bytes"] <= maximum:
        return complete
    selected = None
    minimum_required: int = complete["bounds"]["rendered_bytes"]
    smallest_count = remaining
    smallest_cursor = None
    for count in range(1, remaining):
        _check_deadline(deadline)
        cursor = cursor_for_offset(offset + count) if count < remaining else None
        candidate = _render_page(
            base,
            units,
            offset=offset,
            count=count,
            maximum=maximum,
            cursor=cursor,
            deadline=deadline,
        )
        size = candidate["bounds"]["rendered_bytes"]
        if size < minimum_required:
            minimum_required = size
            smallest_count, smallest_cursor = count, cursor
        if size <= maximum:
            selected = candidate
    if selected is None:
        minimum_required = _minimum_required(
            base,
            units,
            offset=offset,
            count=smallest_count,
            cursor=smallest_cursor,
            deadline=deadline,
            initial=minimum_required,
        )
        raise ContextError(
            422,
            "C1-CX-010",
            "insufficient_budget",
            details={
                "minimum_required": minimum_required,
            },
        )
    return selected


def _minimum_required(
    base: dict[str, Any],
    units: list[dict[str, Any]],
    *,
    offset: int,
    count: int,
    cursor: str | None,
    deadline: float | None,
    initial: int,
) -> int:
    # The suggested retry maximum is itself part of the rendered bounds.
    minimum = initial
    for _ in range(16):
        candidate = _render_page(
            base,
            units,
            offset=offset,
            count=count,
            maximum=minimum,
            cursor=cursor,
            deadline=deadline,
        )
        measured: int = candidate["bounds"]["rendered_bytes"]
        if measured == minimum:
            return minimum
        minimum = measured
    raise RuntimeError("context minimum-budget fixed point did not converge")


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise ContextError(503, "C1-CX-014", "time_budget")
