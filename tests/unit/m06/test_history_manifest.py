"""Document history consumes private copies of a guarded plan manifest."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.audit import Audit
from c1.authorization.fga import FGA, scope_object
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.documents.service import _history_candidates
from c1.query.plan import AuthorizedPlan, AuthorizedSelection, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.storage.terminus import StorageError
from tests.unit.m06.test_document_history import DOC, PRINCIPAL, P, Q, _service


def _attach(runtime: Any, plan: AuthorizedPlan) -> AuthorizedPlan:
    manifest = json.dumps(runtime.journal.list_many.return_value, sort_keys=True).encode()
    selected = replace(plan, history_manifest=manifest)
    runtime.query.selection.return_value = (selected, {})
    return selected


def test_real_planner_supplies_document_manifest_from_one_guarded_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        rows = {
            **runtime.journal.list_many.return_value,
            "Scope": [{"id": "shared", "label": "Shared", "state": "active"}],
            "Binding": [
                {
                    "resource_id": key,
                    "scope_id": "shared",
                    "state": "active",
                    "operation_id": "op",
                }
                for key in original.authorized_ids
            ],
        }

        rows["Operation"] = [
            {
                **operation,
                "id": "op",
                "actor": PRINCIPAL.id,
                "created": "2026-09-28T00:00:00Z",
                "updated": "2026-09-28T00:00:00Z",
            }
            for operation in rows["Operation"]
        ]

        async def enumerate_journal(kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
            return {kind: rows[kind] for kind in kinds}

        runtime.journal.list_many.side_effect = enumerate_journal
        fga = SimpleNamespace(
            list_objects=AsyncMock(return_value=[scope_object("shared")]),
            batch_check=AsyncMock(side_effect=lambda checks: [True] * len(checks)),
            bindings=AsyncMock(return_value=[scope_object("shared")]),
        )
        journal, typed_fga = cast(Journal, runtime.journal), cast(FGA, fga)
        planner = AuthorizedSelection(
            journal, typed_fga, AuthorizationPlane(journal, typed_fga, "test", Audit())
        )

        async def selection(
            principal: Principal, *, deadline: float
        ) -> tuple[AuthorizedPlan, dict[str, Any]]:
            return await planner.build(principal, deadline=deadline), {}

        runtime.query.selection.side_effect = selection
        runtime.query.planner = planner
        assert (await service.history(PRINCIPAL, DOC))["count"] == 3
        runtime.journal.list_many.assert_awaited_once_with(
            {"Scope", "Binding", "ChangeSet", "Operation"}
        )
        selected = runtime.query.records.await_args.args[0]
        assert isinstance(selected.history_manifest, bytes)
        assert fga.batch_check.await_count == 2  # Selection and fresh publication authorization.

    asyncio.run(run())


def test_plan_manifest_avoids_redundant_journal_reads_and_retains_unknown_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        plan = _attach(runtime, original)
        fallback = AsyncMock(side_effect=AssertionError("Plan manifest must supply history"))
        monkeypatch.setattr(service, "_history_manifest", fallback)
        result = await service.history(PRINCIPAL, DOC)
        assert result["count"] == 3
        fallback.assert_not_awaited()
        runtime.journal.head.assert_not_awaited()
        runtime.journal.list_many.assert_not_awaited()
        calls = runtime.changes.history_service.metadata.await_args_list
        hints = {call.args[1]: call.kwargs["storage_types"] for call in calls}
        assert hints[P] is not None
        assert hints[Q] is None  # Creation was not recorded; retain all-class history probes.
        assert "storage_types" not in runtime.query.records.await_args.kwargs
        assert runtime.query.planner.finalize_after.await_args.args[1] is plan

    asyncio.run(run())


@pytest.mark.parametrize(
    "manifest",
    [
        b"not JSON",
        b"\xff",
        b"null",
        b"[]",
        b"{}",
        b'{"ChangeSet": []}',
        b'{"ChangeSet": [], "Operation": [], "unknown": []}',
        b'{"ChangeSet": null, "Operation": []}',
        b'{"ChangeSet": [], "Operation": {}}',
        b'{"ChangeSet": [null], "Operation": []}',
        b'{"ChangeSet": [], "Operation": ["invalid"]}',
    ],
)
def test_invalid_plan_manifest_fails_closed_before_content_or_metadata(
    monkeypatch: pytest.MonkeyPatch, manifest: bytes
) -> None:
    async def run() -> None:
        service, runtime, plan = _service(monkeypatch)
        runtime.query.selection.return_value = (replace(plan, history_manifest=manifest), {})
        with pytest.raises(QueryPlanError) as error:
            await service.history(PRINCIPAL, DOC)
        assert (error.value.status, error.value.code) == (503, "C1-DC-010")
        runtime.journal.list_many.assert_not_awaited()
        runtime.query.records.assert_not_awaited()
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


def test_manifest_nested_mutations_are_isolated_between_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        plan = _attach(runtime, original)
        original_bytes = plan.history_manifest
        manifests: list[dict[str, list[dict[str, Any]]]] = []
        initial_values: list[str] = []

        def candidates(
            identifier: str,
            selected: AuthorizedPlan,
            records: AuthorizedRecords,
            journal: dict[str, list[dict[str, Any]]],
        ) -> tuple[set[str], dict[str, frozenset[str]]]:
            result = _history_candidates(identifier, selected, records, journal)
            if not any(journal is previous for previous in manifests):
                manifests.append(journal)
                initial_values.append(json.dumps(journal, sort_keys=True))
            else:
                journal["ChangeSet"][0]["operations"][0]["record"]["id"] = "urn:mutated"
                journal["Operation"][0]["payload"]["records"][0]["properties"]["urn:local"] = []
            return result

        monkeypatch.setattr("c1.documents.service._history_candidates", candidates)
        assert (await service.history(PRINCIPAL, DOC))["count"] == 3
        assert (await service.history(PRINCIPAL, DOC))["count"] == 3
        assert len(manifests) == 2 and manifests[0] is not manifests[1]
        assert initial_values[0] == initial_values[1]
        assert plan.history_manifest == original_bytes
        assert manifests[0]["ChangeSet"][0]["operations"][0]["record"]["id"] == "urn:mutated"

    asyncio.run(run())


def test_hidden_malformed_payload_never_enters_manifest_candidates_or_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        hidden = "urn:c1:test:hidden-malformed"
        runtime.journal.list_many.return_value["Operation"][0]["payload"]["records"].append(
            {"id": hidden, "types": [], "properties": "invalid"}
        )
        plan = _attach(runtime, original)
        assert not plan.contains(hidden)
        result = await service.history(PRINCIPAL, DOC)
        assert result["count"] == 3 and hidden not in json.dumps(result)
        calls = runtime.changes.history_service.metadata.await_args_list
        assert {call.args[1] for call in calls} == {DOC, P, Q}
        assert runtime.query.planner.finalize_after.await_args.args[1] is plan

    asyncio.run(run())


@pytest.mark.parametrize("primary", ["not_found", "current_error"])
def test_current_fetch_failure_precedes_speculative_metadata_failure_with_plan_manifest(
    monkeypatch: pytest.MonkeyPatch, primary: str
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        _attach(runtime, original)
        metadata_failed = asyncio.Event()
        current_failure = StorageError("C1-ST-003", "current fetch failed")
        finished: set[str] = set()

        async def current(*_args: Any, **_kwargs: Any) -> AuthorizedRecords:
            await metadata_failed.wait()
            if primary == "current_error":
                raise current_failure
            return AuthorizedRecords({}, {})

        async def metadata(_plan: AuthorizedPlan, key: str, *_args: Any, **_kwargs: Any) -> Any:
            try:
                if key == DOC:
                    metadata_failed.set()
                    raise StorageError("C1-ST-003", "metadata failed")
                await asyncio.Event().wait()
            finally:
                finished.add(key)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        with pytest.raises(QueryPlanError if primary == "not_found" else StorageError) as error:
            await service.history(PRINCIPAL, DOC)
        if primary == "current_error":
            assert error.value is current_failure
        else:
            assert isinstance(error.value, QueryPlanError)
            assert (error.value.status, error.value.code) == (404, "C1-DC-404")
        assert finished == {DOC, P, Q}
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())
