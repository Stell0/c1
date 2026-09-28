"""Lossless Unicode text contract for document parts."""

from __future__ import annotations

import hashlib

MAX_UTF8_BYTES = 256 * 1024
_ALLOWED_CONTROL = frozenset("\t\n\r")


def invalid_control(text: str) -> bool:
    return any(
        (ord(char) < 32 and char not in _ALLOWED_CONTROL) or 0x7F <= ord(char) <= 0x9F
        for char in text
    )


def utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def length(text: str) -> int:
    return len(text)
