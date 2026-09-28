"""Bounded concurrent storage-class history reads preserve page semantics."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from c1.changes.history import encode_cursor
from c1.storage.terminus import StorageError
from tests.unit.m04.test_history import _PRINCIPAL, _service


def test_history_probes_all_storage_classes_with_bounded_concurrency(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        document_ids = [f"storage-class-{index}" for index in range(25)]
        monkeypatch.setattr(
            service, "_document_ids", lambda _resource_id, _types=None: document_ids
        )

        active = 0
        maximum_active = 0
        completed: list[str] = []
        rows_by_id = {
            document_ids[0]: [
                {
                    "identifier": "knowledge2",
                    "timestamp": "2026-09-27T12:00:00Z",
                    "message": "legacy",
                }
            ],
            document_ids[1]: [
                {
                    "identifier": "knowledge1",
                    "timestamp": "2026-09-26T12:00:00Z",
                    "message": "legacy",
                }
            ],
            # One revision can be exposed by more than one historical class.
            document_ids[2]: [
                {
                    "identifier": "knowledge2",
                    "timestamp": "2026-09-27T12:00:00Z",
                    "message": "legacy",
                }
            ],
        }

        async def tracked_history(document_id: str) -> list[dict[str, Any]]:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                await asyncio.sleep(0)
                completed.append(document_id)
                return rows_by_id.get(document_id, [])
            finally:
                active -= 1

        knowledge.history = tracked_history  # type: ignore[assignment]

        first = await service.list(_PRINCIPAL, "urn:c1:test:resource", limit=1)
        assert first == {
            "resource_id": "urn:c1:test:resource",
            "revision": "branch:knowledge2",
            "items": [
                {
                    "revision": "branch:knowledge2",
                    "recorded_at": "2026-09-27T12:00:00Z",
                    "changeset_id": None,
                    "attempt": None,
                }
            ],
            "next_cursor": encode_cursor("branch:knowledge2", 1),
        }
        assert set(completed) == set(document_ids)
        assert len(completed) == len(document_ids)
        assert 1 < maximum_active <= 8

        completed.clear()
        second = await service.list(
            _PRINCIPAL,
            "urn:c1:test:resource",
            limit=1,
            cursor=first["next_cursor"],
        )
        assert second == {
            "resource_id": "urn:c1:test:resource",
            "revision": "branch:knowledge2",
            "items": [
                {
                    "revision": "branch:knowledge1",
                    "recorded_at": "2026-09-26T12:00:00Z",
                    "changeset_id": None,
                    "attempt": None,
                }
            ],
            "next_cursor": None,
        }
        assert set(completed) == set(document_ids)

    asyncio.run(run())


def test_history_suppresses_page_when_access_is_revoked_midfetch(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, plane, _journal = _service()
        document_ids = [f"storage-class-{index}" for index in range(25)]
        monkeypatch.setattr(
            service, "_document_ids", lambda _resource_id, _types=None: document_ids
        )
        revoked = False

        async def revoking_history(_document_id: str) -> list[dict[str, Any]]:
            nonlocal revoked
            await asyncio.sleep(0)
            if not revoked:
                revoked = True
                plane.allowed = False
            return [
                {
                    "identifier": "knowledge2",
                    "timestamp": "2026-09-27T12:00:00Z",
                    "message": "legacy",
                }
            ]

        knowledge.history = revoking_history  # type: ignore[method-assign]

        assert await service.list(_PRINCIPAL, "urn:c1:test:resource") is None
        assert revoked
        assert not plane.allowed
        assert plane.calls >= 2

    asyncio.run(run())


def test_concurrent_resources_share_one_backend_gate(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        document_ids = [f"storage-class-{index}" for index in range(25)]
        monkeypatch.setattr(
            service, "_document_ids", lambda _resource_id, _types=None: document_ids
        )
        active = 0
        maximum = 0
        calls = 0

        async def tracked_history(_document_id: str) -> list[dict[str, Any]]:
            nonlocal active, maximum, calls
            active += 1
            calls += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return []
            finally:
                active -= 1

        knowledge.history = tracked_history  # type: ignore[method-assign]
        gate = asyncio.Semaphore(8)
        results = await asyncio.gather(
            *(
                service.list(_PRINCIPAL, f"urn:c1:test:{index}", backend_gate=gate)
                for index in range(4)
            )
        )
        assert all(result is not None for result in results)
        assert 1 < maximum <= 8
        assert active == 0 and calls == 4 * len(document_ids)

    asyncio.run(run())


def test_backend_failure_cancels_and_awaits_sibling_probes(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        document_ids = [f"storage-class-{index}" for index in range(25)]
        monkeypatch.setattr(
            service, "_document_ids", lambda _resource_id, _types=None: document_ids
        )
        failure = StorageError("C1-ST-003", "original failure")
        active = 0
        cancelled = 0
        calls = 0

        async def failing_history(document_id: str) -> list[dict[str, Any]]:
            nonlocal active, cancelled, calls
            active += 1
            calls += 1
            try:
                if document_id == document_ids[0]:
                    await asyncio.sleep(0)
                    raise failure
                await asyncio.Event().wait()
                return []
            except asyncio.CancelledError:
                cancelled += 1
                raise
            finally:
                active -= 1

        knowledge.history = failing_history  # type: ignore[assignment]
        with pytest.raises(StorageError) as caught:
            await service.list(
                _PRINCIPAL, "urn:c1:test:resource", backend_gate=asyncio.Semaphore(8)
            )
        assert caught.value is failure
        assert active == 0 and cancelled == 7 and calls == 8

    asyncio.run(run())


def test_head_change_during_probes_suppresses_page(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        monkeypatch.setattr(service, "_document_ids", lambda _resource_id, _types=None: ["one"])

        async def changed_history(_document_id: str) -> list[dict[str, Any]]:
            knowledge.revision = "branch:changed"
            return knowledge.rows

        knowledge.history = changed_history  # type: ignore[method-assign]
        assert await service.list(_PRINCIPAL, "urn:c1:test:resource") is None

    asyncio.run(run())
