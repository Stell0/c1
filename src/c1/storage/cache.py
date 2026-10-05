"""Bounded caches of immutable backend facts (M14a, ADR-0025).

The record cache holds content, never authorization: decoded records at a
knowledge commit, whose content never changes. Callers authorize every
resource freshly before any cached record is used.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from c1.model.profiles import ProfileRegistry

MISSING = object()
RECORD_CACHE_ENTRIES = 20_000


def registry_key(registry: ProfileRegistry) -> tuple[tuple[str, str, str], ...]:
    """Installed profiles a decoded record depends on."""
    return tuple(
        sorted(
            (name, profile.version, profile.context_fingerprint)
            for name, profile in registry.profiles.items()
        )
    )


class LruCache:
    def __init__(self, max_entries: int) -> None:
        self._entries: OrderedDict[Hashable, object] = OrderedDict()
        self._max_entries = max_entries

    def get(self, key: Hashable) -> object:
        value = self._entries.get(key, MISSING)
        if value is not MISSING:
            self._entries.move_to_end(key)
        return value

    def put(self, key: Hashable, value: object) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


class RecordCache(LruCache):
    """`(commit, registry, id, class hint) -> NodeRecord | None` (None: absent)."""

    def __init__(self, max_entries: int = RECORD_CACHE_ENTRIES) -> None:
        super().__init__(max_entries)
