"""History metadata overlaps current reads without bypassing current authority."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from c1.documents.service import _digest
from c1.model.records import C1
from c1.query.cursor import CursorCodec
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.storage.terminus import StorageError
from tests.unit.m06.test_document_history import (
    DOC,
    HEAD,
    PRINCIPAL,
    P,
    Q,
    _entry,
    _node,
    _records,
    _service,
)


def test_current_fetch_and_manifest_metadata_overlap_under_same_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, plan = _service(monkeypatch)
        original_records: AuthorizedRecords = runtime.query.records.return_value
        original_metadata = runtime.changes.history_service.metadata.side_effect
        current_started, metadata_started, release = (asyncio.Event() for _ in range(3))
        gates: set[int] = set()

        async def current(
            selected: AuthorizedPlan,
            revision: str,
            *,
            deadline: float,
            backend_gate: asyncio.Semaphore,
        ) -> AuthorizedRecords:
            assert selected is plan and revision == HEAD
            assert runtime.query.selection.await_count == 1
            assert runtime.journal.head.await_count == 2
            gates.add(id(backend_gate))
            current_started.set()
            await metadata_started.wait()
            await release.wait()
            return original_records

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            assert selected is plan and revision == HEAD and plan.contains(key)
            assert runtime.journal.head.await_count == 2
            gates.add(id(kwargs["backend_gate"]))
            metadata_started.set()
            await current_started.wait()
            return await original_metadata(selected, key, revision, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        monkeypatch.setattr(service, "_selection", AsyncMock(side_effect=AssertionError("unused")))
        task = asyncio.create_task(service.history(PRINCIPAL, DOC))
        await metadata_started.wait()
        await current_started.wait()
        await asyncio.sleep(0)
        assert not task.done()
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()
        release.set()
        assert (await task)["count"] == 3
        assert len(gates) == 1
        assert runtime.query.planner.finalize_after.await_args.args[1] is plan

    asyncio.run(run())


def test_current_only_legacy_part_is_added_without_narrowing_history_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original_plan = _service(monkeypatch)
        legacy = "urn:c1:test:untracked-current-part"
        records: AuthorizedRecords = runtime.query.records.return_value
        records[legacy] = _node(legacy, "DocumentPart", DOC)
        plan = AuthorizedPlan(
            original_plan.workflow_head,
            original_plan.readable_scopes,
            (*original_plan.authorized_ids, legacy),
            original_plan.scope_by_id,
        )
        runtime.query.selection.return_value = (plan, {})
        original_metadata = runtime.changes.history_service.metadata.side_effect
        current_finished = False

        async def current(*args: Any, **kwargs: Any) -> AuthorizedRecords:
            nonlocal current_finished
            await asyncio.sleep(0)
            current_finished = True
            return records

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            if key == legacy:
                assert current_finished
                assert kwargs["storage_types"] is None
                return {"items": [_entry(4)], "next_cursor": None}
            return await original_metadata(selected, key, revision, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        await service.history(PRINCIPAL, DOC)
        calls = runtime.changes.history_service.metadata.await_args_list
        assert {call.args[1] for call in calls} == {DOC, P, Q, legacy}
        assert runtime.query.planner.finalize_after.await_args.args[1] is plan

    asyncio.run(run())


@pytest.mark.parametrize("early_failure", [False, True])
def test_current_type_expansion_discards_old_metadata_and_refetches_full_hint(
    monkeypatch: pytest.MonkeyPatch, early_failure: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        records: AuthorizedRecords = runtime.query.records.return_value
        records[P] = _node(P, "Source")
        early_finished = asyncio.Event()
        original_metadata = runtime.changes.history_service.metadata.side_effect
        p_calls = 0

        async def current(*args: Any, **kwargs: Any) -> AuthorizedRecords:
            await early_finished.wait()
            return records

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            nonlocal p_calls
            if key == P:
                p_calls += 1
                if p_calls == 1:
                    assert kwargs["storage_types"] == frozenset({C1 + "DocumentPart"})
                    early_finished.set()
                    if early_failure:
                        raise StorageError("C1-ST-003", "obsolete narrowed read")
                    return {"items": [_entry(9)], "next_cursor": None}
                assert kwargs["storage_types"] == frozenset({C1 + "DocumentPart", C1 + "Source"})
            return await original_metadata(selected, key, revision, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        response = await service.history(PRINCIPAL, DOC)
        assert p_calls == 2
        assert "branch:r9" not in {item["revision"] for item in response["items"]}

    asyncio.run(run())


@pytest.mark.parametrize("primary", ["document_missing", "current_failure"])
def test_document_and_current_fetch_errors_precede_early_metadata_failure(
    monkeypatch: pytest.MonkeyPatch, primary: str
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        metadata_failed = asyncio.Event()
        finished: set[str] = set()
        failure = StorageError("C1-ST-003", "current fetch failure")

        async def current(*args: Any, **kwargs: Any) -> AuthorizedRecords:
            await metadata_failed.wait()
            if primary == "current_failure":
                raise failure
            return _records(_node(P, "DocumentPart", DOC))

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            try:
                if key == DOC:
                    metadata_failed.set()
                    raise StorageError("C1-ST-003", "early history failure")
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(key)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        with pytest.raises(
            QueryPlanError if primary == "document_missing" else StorageError
        ) as error:
            await service.history(PRINCIPAL, DOC)
        if primary == "document_missing":
            assert isinstance(error.value, QueryPlanError)
            assert (error.value.status, error.value.code) == (404, "C1-DC-404")
        else:
            assert error.value is failure
        assert finished == {DOC, P, Q}
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


def test_cursor_restart_precedes_any_current_fetch_or_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        runtime.query.codec = CursorCodec("x" * 32)
        cursor = service._next(
            PRINCIPAL, "branch:previous", _digest("document-history", DOC), "history", ("0", "old")
        )
        with pytest.raises(QueryPlanError) as error:
            await service.history(PRINCIPAL, DOC, cursor=cursor)
        assert (error.value.status, error.value.code) == (409, "C1-DC-014")
        runtime.query.records.assert_not_awaited()
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_deadline_or_cancel_cleans_up_current_and_every_early_history_task(
    monkeypatch: pytest.MonkeyPatch, external_cancel: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        runtime.settings.query_time_budget_ms = 2000 if external_cancel else 30
        started: set[str] = set()
        finished: set[str] = set()
        all_started = asyncio.Event()

        async def blocked(name: str) -> None:
            started.add(name)
            if started == {"current", DOC, P, Q}:
                all_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def current(*args: Any, **kwargs: Any) -> AuthorizedRecords:
            await blocked("current")
            raise AssertionError("unreachable")

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            await blocked(key)
            raise AssertionError("unreachable")

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        task = asyncio.create_task(service.history(PRINCIPAL, DOC))
        await all_started.wait()
        if external_cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await task
        assert finished == {"current", DOC, P, Q}
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


def test_current_and_metadata_network_reads_share_global_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        original_records: AuthorizedRecords = runtime.query.records.return_value
        original_metadata = runtime.changes.history_service.metadata.side_effect
        active = maximum = 0

        async def network(gate: asyncio.Semaphore) -> None:
            nonlocal active, maximum
            async with gate:
                active += 1
                maximum = max(maximum, active)
                try:
                    await asyncio.sleep(0.002)
                finally:
                    active -= 1

        async def current(
            selected: AuthorizedPlan,
            revision: str,
            *,
            deadline: float,
            backend_gate: asyncio.Semaphore,
        ) -> AuthorizedRecords:
            await asyncio.gather(*(network(backend_gate) for _ in range(16)))
            return original_records

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            await network(kwargs["backend_gate"])
            return await original_metadata(selected, key, revision, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        await service.history(PRINCIPAL, DOC)
        assert active == 0 and maximum == 8

    asyncio.run(run())


def test_unreadable_or_unknown_document_launches_no_content_or_metadata_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        runtime.query.selection.return_value = (
            AuthorizedPlan(
                original.workflow_head,
                original.readable_scopes,
                tuple(key for key in original.authorized_ids if key != DOC),
                original.scope_by_id,
            ),
            {},
        )

        def forbidden(*args: object, **kwargs: object) -> object:
            raise AssertionError("An unreadable anchor cannot inspect candidate manifests")

        monkeypatch.setattr("c1.documents.service._history_candidates", forbidden)
        with pytest.raises(QueryPlanError) as error:
            await service.history(PRINCIPAL, DOC)
        assert (error.value.status, error.value.code, error.value.reason) == (
            404,
            "C1-DC-404",
            "not_found",
        )
        runtime.query.records.assert_not_awaited()
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("document_present", [False, True])
def test_oversized_early_candidates_do_not_prefetch_and_preserve_document_priority(
    monkeypatch: pytest.MonkeyPatch, document_present: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        # The authorized manifest contains two candidates P and Q. A one-part
        # bound exercises rejection without creating thousands of test tasks.
        monkeypatch.setattr("c1.documents.service.MAX_PARTS", 1)
        if not document_present:
            runtime.query.records.return_value = _records(_node(P, "DocumentPart", DOC))
        with pytest.raises(QueryPlanError) as error:
            await service.history(PRINCIPAL, DOC)
        assert (error.value.status, error.value.code) == (
            (422, "C1-DC-006") if document_present else (404, "C1-DC-404")
        )
        runtime.query.records.assert_awaited_once()
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


def test_bootstrap_enqueues_nested_current_authority_before_metadata_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        original_records: AuthorizedRecords = runtime.query.records.return_value
        original_metadata = runtime.changes.history_service.metadata.side_effect
        entered: list[str] = []

        async def network(gate: asyncio.Semaphore, label: str) -> None:
            async with gate:
                entered.append(label)
                await asyncio.sleep(0)

        async def current(
            selected: AuthorizedPlan,
            revision: str,
            *,
            deadline: float,
            backend_gate: asyncio.Semaphore,
        ) -> AuthorizedRecords:
            async def authority() -> None:
                await asyncio.gather(
                    network(backend_gate, "schema"), network(backend_gate, "marker")
                )

            async def collector() -> None:
                await asyncio.gather(*(network(backend_gate, "content") for _ in range(3)))

            # Match the nested worker shape of ordinary fetch_records, rather
            # than checking merely that the current parent coroutine started.
            authority_task = asyncio.create_task(authority())
            collector_task = asyncio.create_task(collector())
            await asyncio.gather(authority_task, collector_task)
            return original_records

        async def metadata(selected: AuthorizedPlan, key: str, revision: str, **kwargs: Any) -> Any:
            await asyncio.create_task(network(kwargs["backend_gate"], "metadata"))
            return await original_metadata(selected, key, revision, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        await service.history(PRINCIPAL, DOC)
        assert entered[:2] == ["schema", "marker"]
        assert entered.count("content") == entered.count("metadata") == 3

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_cancel_or_deadline_during_bootstrap_cleans_up_current_before_propagating(
    monkeypatch: pytest.MonkeyPatch, external_cancel: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        runtime.settings.query_time_budget_ms = 2000 if external_cancel else 30
        bootstrap_entered, current_started, current_finished = (asyncio.Event() for _ in range(3))

        async def current(*args: Any, **kwargs: Any) -> AuthorizedRecords:
            current_started.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                await asyncio.sleep(0)
                current_finished.set()

        async def bootstrap(delay: float) -> None:
            assert delay == 0
            bootstrap_entered.set()
            await current_started.wait()
            await asyncio.Event().wait()

        # Override only this module's asyncio facade; the test/current cleanup
        # keeps the real scheduler and sleep, including asynchronous finally.
        facade = SimpleNamespace(**vars(asyncio))
        facade.sleep = bootstrap
        monkeypatch.setattr("c1.documents.service.asyncio", facade)
        runtime.query.records.side_effect = current
        task = asyncio.create_task(service.history(PRINCIPAL, DOC))
        await bootstrap_entered.wait()
        await current_started.wait()
        if external_cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await task
        assert current_finished.is_set()
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())
