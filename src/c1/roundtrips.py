"""Per-request backend round-trip counters (M14a A1).

Diagnostics only: the counts never influence a decision. The middleware starts a
fresh counter per HTTP request; tasks spawned during the request share it.
"""

from __future__ import annotations

from contextvars import ContextVar

_COUNTS: ContextVar[dict[str, int] | None] = ContextVar("c1_roundtrips", default=None)


def begin() -> dict[str, int]:
    counts = {"terminus": 0, "openfga": 0}
    _COUNTS.set(counts)
    return counts


def count(backend: str) -> None:
    counts = _COUNTS.get()
    if counts is not None:
        counts[backend] = counts.get(backend, 0) + 1


def current() -> dict[str, int] | None:
    counts = _COUNTS.get()
    return dict(counts) if counts is not None else None
