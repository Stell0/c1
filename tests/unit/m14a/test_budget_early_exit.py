"""M14a C1: prefix sizes grow strictly, so stopping at the first overflow is exact."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from c1.context.budget import _render_page, build_page, prepare_units
from c1.context.errors import ContextError
from tests.unit.m07.test_render_budget import base, unit


def _cursor(offset: int) -> str:
    # Real cursors are signed tokens; their length varies with the offset digits.
    return "c" * 40 + str(offset)


def _sizes(units: list[dict[str, Any]], offset: int = 0) -> list[int]:
    prepared = prepare_units(units)
    return [
        _render_page(
            base(),
            prepared,
            offset=offset,
            count=count,
            maximum=524288,
            cursor=_cursor(offset + count),
            deadline=None,
        )["bounds"]["rendered_bytes"]
        for count in range(1, len(prepared) - offset)
    ]


@pytest.mark.parametrize("excerpt", ["x", "Synthetic battery capacity.", "é" * 400])
def test_prefix_sizes_strictly_increase(excerpt: str) -> None:
    units = [unit(i, excerpt=excerpt) for i in range(12)]
    for offset in (0, 3):
        sizes = _sizes(units, offset)
        assert all(a < b for a, b in zip(sizes, sizes[1:], strict=False)), sizes


def _m13_budget() -> Any:
    """The M13 implementation (exhaustive prefix loop), kept as test data."""
    path = Path(__file__).parent / "data/budget_m13.py"
    spec = importlib.util.spec_from_file_location("c1_budget_m13", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outcome(build: Any, units: list[dict[str, Any]], maximum: int) -> Any:
    try:
        return build(base(), prepare_units(units), maximum=maximum, cursor_for_offset=_cursor)
    except ContextError as error:
        return ("error", error.status, error.code, error.details)


@pytest.mark.parametrize("maximum", [2048, 3000, 4096, 9000, 20000, 65536])
@pytest.mark.parametrize("size", [1, 3, 8])
def test_outputs_equal_the_m13_exhaustive_loop(maximum: int, size: int) -> None:
    units = [unit(i, excerpt="text " * (20 * (i % 3 + 1))) for i in range(size)]
    old = _m13_budget().build_page
    assert _outcome(build_page, units, maximum) == _outcome(old, units, maximum)
