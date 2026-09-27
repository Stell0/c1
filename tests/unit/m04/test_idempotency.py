"""Scoped idempotency key validation and journal replay behavior."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from c1.authorization.journal import Journal
from c1.changes.idempotency import (
    IdempotencyConflict,
    idempotency_address,
    idempotency_entry,
    lookup_idempotency,
    validate_request_key,
)

_DIGEST = "a" * 64


class FakeJournal:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], dict[str, Any]] = {}

    async def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return self.entries.get((kind, key))


def test_key_validation_is_exact_printable_ascii() -> None:
    assert validate_request_key("key with spaces !~") == "key with spaces !~"
    assert validate_request_key("x" * 128) == "x" * 128
    for bad in (None, "", "x" * 129, "line\nfeed", "tab\t", "é", "\x7f"):
        with pytest.raises(ValueError):
            validate_request_key(bad)


def test_scope_address_and_replay_conflict() -> None:
    async def run() -> None:
        journal = FakeJournal()
        first = idempotency_entry(
            "issuer.alice", "knowledge", "same", _DIGEST, "cs-1", {"id": "cs-1"}
        )
        other_principal = idempotency_entry(
            "issuer.bob", "knowledge", "same", _DIGEST, "cs-2", {"id": "cs-2"}
        )
        other_repository = idempotency_entry(
            "issuer.alice", "other", "same", _DIGEST, "cs-3", {"id": "cs-3"}
        )
        assert len({first[1], other_principal[1], other_repository[1]}) == 3
        assert first[1] == idempotency_address("issuer.alice", "knowledge", "same")
        assert (
            await lookup_idempotency(
                cast(Journal, journal), "issuer.alice", "knowledge", "same", _DIGEST
            )
            is None
        )
        journal.entries[(first[0], first[1])] = first[2]
        assert await lookup_idempotency(
            cast(Journal, journal), "issuer.alice", "knowledge", "same", _DIGEST
        ) == {"id": "cs-1", "replayed": True}
        with pytest.raises(IdempotencyConflict, match="idempotency_conflict"):
            await lookup_idempotency(
                cast(Journal, journal), "issuer.alice", "knowledge", "same", "b" * 64
            )

    asyncio.run(run())
