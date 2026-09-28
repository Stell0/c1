"""M06-D1 bounded fractional order keys."""

from __future__ import annotations

import pytest

from c1.documents.order import MAX_LENGTH, between, valid


@pytest.mark.parametrize("key", ["1", "01", "A", "z" * MAX_LENGTH, "1A0z"])
def test_valid_keys(key: str) -> None:
    assert valid(key)


@pytest.mark.parametrize("key", ["", "0", "10", "_", "é", "z" * (MAX_LENGTH + 1)])
def test_invalid_keys(key: str) -> None:
    assert not valid(key)


@pytest.mark.parametrize(
    ("left", "right"),
    [(None, None), (None, "1"), ("1", None), ("1", "2"), ("1", "11"), ("09", "1")],
)
def test_between_returns_strictly_ordered_key(left: str | None, right: str | None) -> None:
    candidate = between(left, right)
    assert valid(candidate)
    assert left is None or left < candidate
    assert right is None or candidate < right


def test_repeated_insertion_reaches_explicit_exhaustion() -> None:
    right = "1"
    for _ in range(MAX_LENGTH - 1):
        right = between(None, right)
    assert right == "0" * (MAX_LENGTH - 1) + "1"
    with pytest.raises(ValueError, match="no order key"):
        between(None, right)


def test_invalid_neighbors_are_rejected() -> None:
    with pytest.raises(ValueError):
        between("0", "1")
    with pytest.raises(ValueError):
        between("2", "1")
