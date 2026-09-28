"""Bounded, byte-sortable document part order keys."""

from __future__ import annotations

import re

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MAX_LENGTH = 64
_KEY = re.compile(r"[0-9A-Za-z]{1,64}")


def valid(key: str) -> bool:
    return bool(_KEY.fullmatch(key)) and not key.endswith("0")


def _increment_fixed(value: str) -> str | None:
    """Smallest valid same-length key greater than value, if one exists."""
    digits = [ALPHABET.index(char) for char in value]
    for index in range(len(digits) - 1, -1, -1):
        if digits[index] == len(ALPHABET) - 1:
            continue
        digits[index] += 1
        digits[index + 1 :] = [0] * (len(digits) - index - 1)
        if digits[-1] == 0:
            digits[-1] = 1
        return "".join(ALPHABET[digit] for digit in digits)
    return None


def between(left: str | None, right: str | None) -> str:
    """Return a short key in the open interval, or raise on finite exhaustion.

    The allowed grammar is finite. An interval can be exhausted near the
    64-character limit, so callers must handle ``ValueError`` explicitly.
    """
    if left is not None and not valid(left):
        raise ValueError("invalid left order key")
    if right is not None and not valid(right):
        raise ValueError("invalid right order key")
    if left is not None and right is not None and left >= right:
        raise ValueError("order keys are not increasing")
    for length in range(1, MAX_LENGTH + 1):
        candidate: str | None
        if left is None:
            candidate = "0" * (length - 1) + "1"
        elif length > len(left):
            candidate = left + "0" * (length - len(left) - 1) + "1"
        else:
            candidate = _increment_fixed(left[:length])
        if candidate is not None and (right is None or candidate < right):
            return candidate
    raise ValueError("no order key available between neighbors")
