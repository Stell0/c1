"""Per-request backend round trips and phase timing (M14a A1, M14b D1).

Diagnostics only: nothing here influences a decision. The middleware starts a
fresh record per HTTP request; tasks spawned during the request share it.
Phase and backend times are wall-clock sums; concurrent work overlaps, so they
can exceed the request's duration.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


@dataclass
class _Record:
    counts: dict[str, int] = field(default_factory=lambda: {"terminus": 0, "openfga": 0})
    backend_ms: dict[str, float] = field(default_factory=dict)
    phases_ms: dict[str, float] = field(default_factory=dict)


_RECORD: ContextVar[_Record | None] = ContextVar("c1_roundtrips", default=None)


def begin() -> dict[str, int]:
    record = _Record()
    _RECORD.set(record)
    return record.counts


def count(backend: str) -> None:
    record = _RECORD.get()
    if record is not None:
        record.counts[backend] = record.counts.get(backend, 0) + 1


@contextmanager
def timed(backend: str) -> Iterator[None]:
    """Count one backend call and add its wall time."""
    count(backend)
    started = time.perf_counter()
    try:
        yield
    finally:
        _add("backend_ms", backend, started)


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Add the wall time of one named phase of the current request."""
    started = time.perf_counter()
    try:
        yield
    finally:
        _add("phases_ms", name, started)


def _add(kind: str, key: str, started: float) -> None:
    record = _RECORD.get()
    if record is not None:
        values = getattr(record, kind)
        values[key] = values.get(key, 0.0) + (time.perf_counter() - started) * 1000


def current() -> dict[str, int] | None:
    record = _RECORD.get()
    return dict(record.counts) if record is not None else None


def timings() -> dict[str, dict[str, float]]:
    record = _RECORD.get()
    if record is None:
        return {}
    return {
        "backend_ms": {k: round(v, 1) for k, v in sorted(record.backend_ms.items())},
        "phases_ms": {k: round(v, 1) for k, v in sorted(record.phases_ms.items())},
    }


Async = Callable[P, Coroutine[Any, Any, T]]


def phased(name: str) -> Callable[[Async[P, T]], Async[P, T]]:
    """Decorate an async function so each call adds its wall time to `name`."""

    def wrap(function: Async[P, T]) -> Async[P, T]:
        @functools.wraps(function)
        async def inner(*args: P.args, **kwargs: P.kwargs) -> T:
            with phase(name):
                return await function(*args, **kwargs)

        return inner

    return wrap
