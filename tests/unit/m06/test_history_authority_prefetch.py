"""Document history owns its first cohort's independent authority preparation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import Mock

import pytest

from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.storage.terminus import StorageError
from tests.unit.m06.test_document_history import DOC, HEAD, PRINCIPAL, P, Q, _entry, _service


class Preparation:
    def __init__(
        self,
        plan: AuthorizedPlan,
        work: Coroutine[Any, Any, None],
        deadline: float,
        gate: asyncio.Semaphore,
    ) -> None:
        self.plan = plan
        self.task: asyncio.Task[None] = asyncio.create_task(work)
        self.deadline = deadline
        self.gate = gate
        self.consumed = False
        self.closes = 0

    async def consume(self, plan: AuthorizedPlan) -> None:
        assert plan is self.plan and not self.consumed
        self.consumed = True
        await self.task

    async def close(self) -> None:
        self.closes += 1
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


def install(
    runtime: Any, work: Callable[[], Coroutine[Any, Any, None]]
) -> tuple[Mock, list[Preparation]]:
    preparations: list[Preparation] = []
    original_cohort = runtime.query.historical_records.side_effect

    def prepare(
        plan: AuthorizedPlan, *, deadline: float, backend_gate: asyncio.Semaphore
    ) -> Preparation:
        result = Preparation(plan, work(), deadline, backend_gate)
        preparations.append(result)
        return result

    async def cohort(plan: AuthorizedPlan, revisions: list[str], **kwargs: Any) -> Any:
        preparation = kwargs.get("preparation")
        if preparation is not None:
            assert preparation.deadline == kwargs["deadline"]
            assert preparation.gate is kwargs["backend_gate"]
            await preparation.consume(plan)
        return await original_cohort(plan, revisions, **kwargs)

    mocked = Mock(side_effect=prepare)
    runtime.query.prepare_historical_records = mocked
    runtime.query.historical_records.side_effect = cohort
    return mocked, preparations


def test_preparation_starts_after_current_success_and_overlaps_pending_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        records: AuthorizedRecords = runtime.query.records.return_value
        original_metadata = runtime.changes.history_service.metadata.side_effect
        current_started, metadata_started, release_current, release_metadata = (
            asyncio.Event() for _ in range(4)
        )
        authority_started, release_authority, cohort_started = (asyncio.Event() for _ in range(3))

        async def authority() -> None:
            authority_started.set()
            await release_authority.wait()

        prepare, preparations = install(runtime, authority)
        original_cohort = runtime.query.historical_records.side_effect

        async def current(*_args: Any, **_kwargs: Any) -> AuthorizedRecords:
            current_started.set()
            await release_current.wait()
            return records

        async def metadata(*args: Any, **kwargs: Any) -> Any:
            metadata_started.set()
            await release_metadata.wait()
            return await original_metadata(*args, **kwargs)

        async def cohort(*args: Any, **kwargs: Any) -> Any:
            cohort_started.set()
            return await original_cohort(*args, **kwargs)

        runtime.query.records.side_effect = current
        runtime.changes.history_service.metadata.side_effect = metadata
        runtime.query.historical_records.side_effect = cohort
        task = asyncio.create_task(service.history(PRINCIPAL, DOC))
        await current_started.wait()
        await metadata_started.wait()
        prepare.assert_not_called()
        release_current.set()
        await authority_started.wait()
        assert not task.done()
        runtime.query.historical_records.assert_not_awaited()
        release_metadata.set()
        await cohort_started.wait()
        assert not task.done()  # Metadata succeeded, but the new authority is still pending.
        release_authority.set()
        assert (await task)["count"] == 3
        assert len(preparations) == 1 and preparations[0].consumed
        assert preparations[0].closes == 1 and preparations[0].task.done()
        assert runtime.query.planner.finalize_after.await_args.args[1] is original
        assert "storage_types" not in runtime.query.records.await_args.kwargs

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["not_found", "current_error", "candidate_limit"])
def test_preparation_never_starts_before_document_and_candidate_validation(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        prepare = runtime.query.prepare_historical_records
        if failure == "not_found":
            runtime.query.records.return_value = AuthorizedRecords({}, {})
        elif failure == "current_error":
            runtime.query.records.side_effect = StorageError("C1-ST-003", "current failed")
        else:
            monkeypatch.setattr("c1.documents.service.MAX_PARTS", 1)
        with pytest.raises(StorageError if failure == "current_error" else QueryPlanError):
            await service.history(PRINCIPAL, DOC)
        prepare.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("authority_failed", [False, True])
def test_metadata_error_keeps_priority_and_closes_pending_or_failed_preparation(
    monkeypatch: pytest.MonkeyPatch, authority_failed: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        authority_ready, authority_finished = asyncio.Event(), asyncio.Event()
        metadata_failure = StorageError("C1-ST-003", "metadata failed")

        async def authority() -> None:
            try:
                authority_ready.set()
                if authority_failed:
                    raise StorageError("C1-ST-006", "new authority failed")
                await asyncio.Event().wait()
            finally:
                authority_finished.set()

        _prepare, preparations = install(runtime, authority)

        async def metadata(_plan: AuthorizedPlan, key: str, *_args: Any, **_kwargs: Any) -> Any:
            await authority_ready.wait()
            if authority_failed:
                await authority_finished.wait()
            if key == DOC:
                raise metadata_failure
            await asyncio.Event().wait()

        runtime.changes.history_service.metadata.side_effect = metadata
        with pytest.raises(StorageError) as error:
            await service.history(PRINCIPAL, DOC)
        assert error.value is metadata_failure
        assert authority_finished.is_set()
        assert len(preparations) == 1 and preparations[0].closes == 1
        assert preparations[0].task.done() and not preparations[0].consumed
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("authority_failed", [False, True])
def test_no_missing_revisions_closes_unused_authority_without_changing_result(
    monkeypatch: pytest.MonkeyPatch, authority_failed: bool
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        ready, finished = asyncio.Event(), asyncio.Event()

        async def authority() -> None:
            try:
                ready.set()
                if authority_failed:
                    raise StorageError("C1-ST-006", "unused authority failed")
                await asyncio.Event().wait()
            finally:
                finished.set()

        _prepare, preparations = install(runtime, authority)

        async def metadata(*_args: Any, **_kwargs: Any) -> Any:
            await ready.wait()
            if authority_failed:
                await finished.wait()
            return {"items": [_entry(4)], "next_cursor": None}

        runtime.changes.history_service.metadata.side_effect = metadata
        response = await service.history(PRINCIPAL, DOC)
        assert response["count"] == 1 and response["items"][0]["revision"] == HEAD
        assert finished.is_set()
        assert preparations[0].closes == 1 and preparations[0].task.done()
        assert not preparations[0].consumed
        runtime.query.historical_records.assert_not_awaited()
        runtime.query.planner.finalize_after.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_cancel_or_deadline_pending_metadata_closes_authority_and_every_history_task(
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
            if started == {"authority", DOC, P, Q}:
                all_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        _prepare, preparations = install(runtime, lambda: blocked("authority"))

        async def metadata(_plan: AuthorizedPlan, key: str, *_args: Any, **_kwargs: Any) -> Any:
            await blocked(key)
            raise AssertionError("unreachable")

        runtime.changes.history_service.metadata.side_effect = metadata
        task = asyncio.create_task(service.history(PRINCIPAL, DOC))
        await all_started.wait()
        if external_cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if external_cancel else TimeoutError):
            await task
        assert finished == {"authority", DOC, P, Q}
        assert preparations[0].closes == 1 and preparations[0].task.done()
        runtime.query.historical_records.assert_not_awaited()

    asyncio.run(run())


def test_revision_union_bound_closes_preparation_before_any_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        monkeypatch.setattr("c1.documents.service.MAX_PARTS", 4)
        ready, finished = asyncio.Event(), asyncio.Event()

        async def authority() -> None:
            try:
                ready.set()
                await asyncio.Event().wait()
            finally:
                finished.set()

        _prepare, preparations = install(runtime, authority)

        async def metadata(_plan: AuthorizedPlan, key: str, *_args: Any, **_kwargs: Any) -> Any:
            await ready.wait()
            indexes = range(1, 5) if key == P else range(5, 9) if key == Q else [0]
            return {"items": [_entry(index) for index in indexes], "next_cursor": None}

        runtime.changes.history_service.metadata.side_effect = metadata
        with pytest.raises(QueryPlanError) as error:
            await service.history(PRINCIPAL, DOC)
        assert (error.value.status, error.value.code) == (422, "C1-DC-006")
        assert finished.is_set() and preparations[0].closes == 1
        runtime.query.historical_records.assert_not_awaited()

    asyncio.run(run())


def test_only_first_cohort_consumes_preparation_and_each_request_gets_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        records: AuthorizedRecords = runtime.query.records.return_value

        async def authority() -> None:
            return None

        _prepare, preparations = install(runtime, authority)

        async def metadata(_plan: AuthorizedPlan, key: str, *_args: Any, **_kwargs: Any) -> Any:
            indexes = range(1, 11) if key == P else [4]
            return {"items": [_entry(index) for index in indexes], "next_cursor": None}

        async def cohort(
            plan: AuthorizedPlan, revisions: list[str], **kwargs: Any
        ) -> dict[str, AuthorizedRecords]:
            preparation = kwargs["preparation"]
            if preparation is not None:
                await preparation.consume(plan)
            return {revision: records for revision in revisions}

        runtime.changes.history_service.metadata.side_effect = metadata
        runtime.query.historical_records.side_effect = cohort
        await service.history(PRINCIPAL, DOC)
        await service.history(PRINCIPAL, DOC)
        assert len(preparations) == 2 and preparations[0] is not preparations[1]
        assert all(item.consumed and item.closes == 1 for item in preparations)
        calls = runtime.query.historical_records.await_args_list
        assert [len(call.args[1]) for call in calls] == [8, 1, 8, 1]
        assert [call.kwargs["preparation"] for call in calls] == [
            preparations[0],
            None,
            preparations[1],
            None,
        ]
        assert all(
            call.args[0] is preparations[index // 2].plan for index, call in enumerate(calls)
        )

    asyncio.run(run())


def test_preparation_and_first_cohort_share_existing_narrowed_plan_and_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, original = _service(monkeypatch)
        runtime.journal.list_many.return_value["ChangeSet"][0]["operations"].append(
            {"kind": "create", "record": {"id": Q}}
        )

        async def authority() -> None:
            return None

        prepare, preparations = install(runtime, authority)
        await service.history(PRINCIPAL, DOC)
        selected = prepare.call_args.args[0]
        assert selected is not original and set(selected.authorized_ids) == {DOC, P, Q}
        call = runtime.query.historical_records.await_args
        assert call.args[0] is selected and call.kwargs["preparation"] is preparations[0]
        assert (
            call.kwargs["backend_gate"] is runtime.query.records.await_args.kwargs["backend_gate"]
        )
        assert runtime.query.planner.finalize_after.await_args.args[1] is original

    asyncio.run(run())


def test_cohort_error_closes_pending_preparation_and_keeps_original_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        ready, finished = asyncio.Event(), asyncio.Event()
        failure = StorageError("C1-ST-005", "historical content failed")

        async def authority() -> None:
            try:
                ready.set()
                await asyncio.Event().wait()
            finally:
                finished.set()

        _prepare, preparations = install(runtime, authority)

        async def failed_cohort(*_args: Any, **_kwargs: Any) -> Any:
            await ready.wait()
            raise failure

        runtime.query.historical_records.side_effect = failed_cohort
        with pytest.raises(StorageError) as error:
            await service.history(PRINCIPAL, DOC)
        assert error.value is failure
        assert finished.is_set() and preparations[0].closes == 1
        runtime.query.planner.finalize_after.assert_not_awaited()

    asyncio.run(run())
