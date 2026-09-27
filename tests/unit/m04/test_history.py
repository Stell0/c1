"""Current bindings and revision-bound history cursors."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

from c1.authorization.journal import Journal
from c1.authorization.models import Decision
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.changes.history import (
    HistoryService,
    InvalidHistoryCursor,
    StaleHistoryCursor,
    _history_entry,
    decode_cursor,
    encode_cursor,
)
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import StorageConfig, StorageError, Terminus

_RESOURCE = "urn:c1:test:resource"
_PRINCIPAL = Principal("test", "alice", "human")


class FakeJournal:
    revision = "branch:workflow1"

    async def head(self) -> str:
        return self.revision


class FakePlane:
    def __init__(self) -> None:
        self.allowed = True
        self.calls = 0

    async def check_read(self, _principal: Principal, _resource_id: str) -> Decision:
        self.calls += 1
        return Decision(self.allowed, "allowed" if self.allowed else "permission_denied")


class FakeKnowledge:
    def __init__(self) -> None:
        self.config = StorageConfig(
            "http://localhost:6363", "pass", "admin", "c1_m03_test", "urn:c1:instance:dev:"
        )
        self.revision = "branch:knowledge2"
        self.history_calls = 0
        self.rows: list[dict[str, Any]] = [
            {
                "identifier": "knowledge2",
                "timestamp": "2026-09-27T12:00:00Z",
                "message": json.dumps({"c1": 2, "changeset": "cs-2", "attempt": 1}),
            },
            {"identifier": "knowledge1", "timestamp": "2026-09-26T12:00:00Z", "message": "legacy"},
        ]

    async def head(self) -> str:
        return self.revision

    async def history(self, _document_id: str) -> list[dict[str, Any]]:
        self.history_calls += 1
        return self.rows if self.history_calls == 1 else []

    async def get_record(
        self, resource_id: str, _registry: ProfileRegistry, commit: str | None = None
    ) -> NodeRecord:
        return NodeRecord(id=resource_id, types=["urn:c1:ns:core#Entity"], properties={})


def _service() -> tuple[HistoryService, FakeKnowledge, FakePlane, FakeJournal]:
    knowledge = FakeKnowledge()
    plane = FakePlane()
    journal = FakeJournal()
    service = HistoryService(
        cast(Terminus, knowledge),
        cast(AuthorizationPlane, plane),
        cast(Journal, journal),
        ProfileRegistry(),
    )
    return service, knowledge, plane, journal


def test_cursor_rejects_malformed_content() -> None:
    value = encode_cursor("branch:one", 4)
    assert decode_cursor(value) == ("branch:one", 4)
    for bad in ("", "*", "e30", encode_cursor("branch:one", 1) + "="):
        with pytest.raises(InvalidHistoryCursor):
            decode_cursor(bad)


def test_pinned_numeric_timestamp_is_rendered_in_utc() -> None:
    entry = _history_entry({"identifier": "one", "timestamp": 0.5, "message": "legacy"})
    assert entry["recorded_at"] == "1970-01-01T00:00:00.500000Z"
    invalid_timestamps: list[Any] = [True, float("nan"), float("inf"), {}, []]
    for invalid in invalid_timestamps:
        with pytest.raises(StorageError, match="invalid history timestamp"):
            _history_entry({"identifier": "one", "timestamp": invalid})


def test_history_is_paged_and_reauthorizes_every_request() -> None:
    async def run() -> None:
        service, knowledge, plane, _journal = _service()
        first = await service.list(_PRINCIPAL, _RESOURCE, limit=1)
        assert first is not None
        assert first["items"] == [
            {
                "revision": "branch:knowledge2",
                "recorded_at": "2026-09-27T12:00:00Z",
                "changeset_id": "cs-2",
                "attempt": 1,
            }
        ]
        assert first["next_cursor"] is not None
        assert plane.calls >= 2
        knowledge.history_calls = 0
        second = await service.list(_PRINCIPAL, _RESOURCE, limit=1, cursor=first["next_cursor"])
        assert second is not None and second["items"][0]["changeset_id"] is None
        assert second["next_cursor"] is None
        plane.allowed = False
        calls_before = knowledge.history_calls
        assert await service.list(_PRINCIPAL, _RESOURCE, cursor=first["next_cursor"]) is None
        assert knowledge.history_calls == calls_before

    asyncio.run(run())


def test_stale_cursor_and_security_change_fail_closed() -> None:
    async def run() -> None:
        service, knowledge, plane, journal = _service()
        knowledge.revision = "branch:newhead"
        with pytest.raises(StaleHistoryCursor):
            await service.list(_PRINCIPAL, _RESOURCE, cursor=encode_cursor("branch:oldhead", 0))
        knowledge.revision = "branch:knowledge2"

        original = knowledge.history

        async def changed_history(document_id: str) -> list[dict[str, Any]]:
            journal.revision = "branch:workflow2"
            return await original(document_id)

        knowledge.history = changed_history  # type: ignore[assignment]
        assert await service.list(_PRINCIPAL, _RESOURCE) is None
        assert plane.calls >= 2

    asyncio.run(run())


def test_restore_checks_historical_content_under_current_binding() -> None:
    async def run() -> None:
        service, _knowledge, plane, _journal = _service()
        exact = NodeRecord(id=_RESOURCE, types=["urn:c1:ns:core#Entity"], properties={})
        assert await service.restore_matches(_PRINCIPAL, _RESOURCE, "branch:old", exact)
        changed = NodeRecord(id=_RESOURCE, types=["urn:c1:ns:core#Source"], properties={})
        assert not await service.restore_matches(_PRINCIPAL, _RESOURCE, "branch:old", changed)
        plane.allowed = False
        assert not await service.restore_matches(_PRINCIPAL, _RESOURCE, "branch:old", exact)

    asyncio.run(run())


def test_revocation_during_history_selection_suppresses_page() -> None:
    async def run() -> None:
        service, knowledge, plane, _journal = _service()
        original = knowledge.history

        async def revoking_history(document_id: str) -> list[dict[str, Any]]:
            result = await original(document_id)
            plane.allowed = False
            return result

        knowledge.history = revoking_history  # type: ignore[assignment]
        assert await service.list(_PRINCIPAL, _RESOURCE) is None
        assert plane.calls >= 2

    asyncio.run(run())
