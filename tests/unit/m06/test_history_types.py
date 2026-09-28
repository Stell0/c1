"""Trusted history type hints narrow probes without inventing history entries."""

from __future__ import annotations

import asyncio
from typing import Any

from c1.query.plan import AuthorizedPlan
from tests.unit.m04.test_history import _PRINCIPAL, _RESOURCE, _service

CORE = "urn:c1:ns:core#"


def test_known_type_hint_probes_only_its_storage_class() -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        all_ids = service._document_ids(_RESOURCE)
        hinted_ids = service._document_ids(_RESOURCE, frozenset({CORE + "DocumentPart"}))
        assert len(hinted_ids) == 1 < len(all_ids)
        result = await service.list(
            _PRINCIPAL, _RESOURCE, storage_types=frozenset({CORE + "DocumentPart"})
        )
        assert result is not None and len(result["items"]) == 2
        assert knowledge.history_calls == 1

    asyncio.run(run())


def test_multiple_known_types_union_actual_backend_history() -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        types = frozenset({CORE + "Document", CORE + "DocumentPart"})
        ids = service._document_ids(_RESOURCE, types)
        assert len(ids) == 2
        rows_by_id = {
            ids[0]: [{"identifier": "older", "timestamp": 1, "message": "legacy"}],
            ids[1]: [{"identifier": "newer", "timestamp": 2, "message": "legacy"}],
        }
        calls: list[str] = []

        async def class_history(document_id: str) -> list[dict[str, Any]]:
            calls.append(document_id)
            return rows_by_id[document_id]

        knowledge.history = class_history  # type: ignore[assignment]
        result = await service.list(_PRINCIPAL, _RESOURCE, storage_types=types)
        assert result is not None
        assert [entry["revision"] for entry in result["items"]] == ["branch:newer", "branch:older"]
        assert result["items"][0]["recorded_at"] == "1970-01-01T00:00:02.000000Z"
        assert set(calls) == set(ids)

    asyncio.run(run())


def test_unknown_empty_and_missing_hints_preserve_full_probe_coverage() -> None:
    async def run() -> None:
        service, knowledge, _plane, _journal = _service()
        expected = service._document_ids(_RESOURCE)
        for hint in (
            None,
            frozenset(),
            frozenset({"urn:c1:unknown:class"}),
            frozenset({CORE + "DocumentPart", "urn:c1:unknown:class"}),
        ):
            assert service._document_ids(_RESOURCE, hint) == expected
            knowledge.history_calls = 0
            result = await service.list(_PRINCIPAL, _RESOURCE, storage_types=hint)
            assert result is not None
            assert knowledge.history_calls == len(expected)

    asyncio.run(run())


def test_metadata_requires_plan_membership_before_backend_calls(monkeypatch: Any) -> None:
    async def run() -> None:
        service, knowledge, plane, journal = _service()
        plan = AuthorizedPlan("security-head", frozenset(), (), {})

        async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("Unauthorized metadata must not fetch backend or security state")

        monkeypatch.setattr(knowledge, "head", forbidden)
        monkeypatch.setattr(knowledge, "history", forbidden)
        monkeypatch.setattr(journal, "head", forbidden)
        assert await service.metadata(plan, _RESOURCE, "branch:knowledge2") is None
        assert plane.calls == 0

    asyncio.run(run())


def test_default_and_typed_metadata_match_guarded_list_results() -> None:
    async def run() -> None:
        for types in (None, frozenset({CORE + "DocumentPart"})):
            service, knowledge, plane, _journal = _service()
            plan = AuthorizedPlan("security-head", frozenset(), (_RESOURCE,), {})
            expected = await service.list(_PRINCIPAL, _RESOURCE, limit=100, storage_types=types)
            knowledge.history_calls = 0
            checks_before = plane.calls
            actual = await service.metadata(
                plan, _RESOURCE, "branch:knowledge2", storage_types=types
            )
            assert actual == expected
            assert plane.calls == checks_before
            assert knowledge.history_calls == len(service._document_ids(_RESOURCE, types))

    asyncio.run(run())
