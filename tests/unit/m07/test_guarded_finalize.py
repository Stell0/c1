"""Publication waits retain a fresh security barrier and owned-task cleanup."""

from __future__ import annotations

import asyncio
import gc
import time
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock

import pytest

from c1.authorization.principal import Principal
from c1.query.plan import QueryPlanError
from c1.storage.terminus import BackendError
from tests.unit.m07.test_finalize_concurrency import PLAN
from tests.unit.m07.test_plan_concurrency import PRINCIPAL, FGAFake, JournalFake, planner


def test_workflow_revocation_during_unchanged_knowledge_wait_rejects_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        journal = JournalFake()
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        knowledge_started, release_knowledge = asyncio.Event(), asyncio.Event()
        authorized, initial_read = asyncio.Event(), asyncio.Event()
        knowledge_head = "knowledge1"
        heads = 0
        original_authorize = selected._authorize

        async def knowledge() -> None:
            knowledge_started.set()
            await release_knowledge.wait()
            assert knowledge_head == "knowledge1"

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            result = await original_authorize(principal, ids, scope_by_id)
            authorized.set()
            return result

        async def head() -> str:
            nonlocal heads
            heads += 1
            result = journal.value
            if heads == 1:
                initial_read.set()
            return result

        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        task = asyncio.create_task(selected.finalize_after(PRINCIPAL, PLAN, knowledge))
        await asyncio.gather(knowledge_started.wait(), authorized.wait(), initial_read.wait())
        assert fga.checks == 1 and heads == 1 and not task.done()
        # A supported security mutation advances workflow state, not knowledge.
        fga.allow = False
        journal.value = "head2"
        release_knowledge.set()
        with pytest.raises(QueryPlanError) as error:
            await task
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")
        assert knowledge_head == "knowledge1" and heads == 2

    asyncio.run(run())


@pytest.mark.parametrize("blocked", ["knowledge", "authorization", "initial_head"])
def test_last_workflow_read_waits_for_every_successful_prerequisite(
    monkeypatch: pytest.MonkeyPatch, blocked: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        started = {name: asyncio.Event() for name in ("knowledge", "authorization", "initial_head")}
        release, last_started, release_last = (asyncio.Event() for _ in range(3))
        heads = 0

        async def prerequisite(name: str) -> None:
            started[name].set()
            if name == blocked:
                await release.wait()

        async def knowledge() -> None:
            await prerequisite("knowledge")

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            assert (principal, ids, scope_by_id) == (
                PRINCIPAL,
                PLAN.authorized_ids,
                PLAN.scope_by_id,
            )
            await prerequisite("authorization")
            return ids

        async def head() -> str:
            nonlocal heads
            heads += 1
            if heads == 1:
                await prerequisite("initial_head")
            else:
                last_started.set()
                await release_last.wait()
            return "head1"

        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        task = asyncio.create_task(selected.finalize_after(PRINCIPAL, PLAN, knowledge))
        await asyncio.gather(*(event.wait() for event in started.values()))
        assert heads == 1 and not last_started.is_set() and not task.done()
        release.set()
        await last_started.wait()
        assert not task.done()
        release_last.set()
        await task
        assert heads == 2

    asyncio.run(run())


@pytest.mark.parametrize("failure_kind", ["knowledge_changed", "backend", "timeout"])
@pytest.mark.parametrize("initial_outcome", ["error", "mismatch"])
def test_precondition_error_identity_precedes_completed_security_failures(
    monkeypatch: pytest.MonkeyPatch, failure_kind: str, initial_outcome: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        auth_finished, head_finished = asyncio.Event(), asyncio.Event()
        primary: Exception = {
            "knowledge_changed": QueryPlanError(409, "C1-DC-014", "restart_required"),
            "backend": BackendError(503, "synthetic_unavailable"),
            "timeout": TimeoutError("knowledge deadline"),
        }[failure_kind]
        unhandled: list[dict[str, Any]] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: unhandled.append(context)
        )
        head = AsyncMock()

        async def knowledge() -> None:
            await asyncio.gather(auth_finished.wait(), head_finished.wait())
            raise primary

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            try:
                raise RuntimeError("authorization unavailable")
            finally:
                auth_finished.set()

        async def initial_head() -> str:
            try:
                if initial_outcome == "error":
                    raise RuntimeError("workflow unavailable")
                return "head2"
            finally:
                head_finished.set()

        head.side_effect = initial_head
        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        with pytest.raises(type(primary)) as error:
            await selected.finalize_after(PRINCIPAL, PLAN, knowledge)
        assert error.value is primary
        head.assert_awaited_once()
        # Release the failed finalization frame before checking task diagnostics.
        primary.__traceback__ = None
        del error
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == []

    asyncio.run(run())


@pytest.mark.parametrize("failure_kind", ["knowledge_changed", "backend", "timeout"])
def test_precondition_failure_cancels_and_awaits_running_authority_checks(
    monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        auth_started, head_started = asyncio.Event(), asyncio.Event()
        finished: set[str] = set()
        primary: Exception = {
            "knowledge_changed": QueryPlanError(409, "C1-DC-014", "restart_required"),
            "backend": BackendError(503),
            "timeout": TimeoutError("knowledge deadline"),
        }[failure_kind]

        async def blocked(name: str, started: asyncio.Event) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def knowledge() -> None:
            await asyncio.gather(auth_started.wait(), head_started.wait())
            raise primary

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            await blocked("authorization", auth_started)
            raise AssertionError("unreachable")

        async def head() -> str:
            await blocked("head", head_started)
            raise AssertionError("unreachable")

        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        with pytest.raises(type(primary)) as error:
            await selected.finalize_after(PRINCIPAL, PLAN, knowledge)
        assert error.value is primary
        assert finished == {"authorization", "head"}

    asyncio.run(run())


def test_expired_deadline_never_invokes_factory_or_starts_authority_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        factory, head, authorize = AsyncMock(), AsyncMock(), AsyncMock()
        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize_after(PRINCIPAL, PLAN, factory, deadline=time.monotonic() - 1)
        assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        factory.assert_not_called()
        head.assert_not_called()
        authorize.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome", ["auth_deny", "auth_error", "initial_error", "initial_mismatch"]
)
def test_failed_prerequisite_never_starts_final_workflow_read(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        primary = RuntimeError("authority unavailable")
        head = AsyncMock(return_value="head2" if outcome == "initial_mismatch" else "head1")
        authorize = AsyncMock(return_value=() if outcome == "auth_deny" else PLAN.authorized_ids)
        if outcome == "auth_error":
            authorize.side_effect = primary
        elif outcome == "initial_error":
            head.side_effect = primary
        knowledge = AsyncMock()
        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize_after(PRINCIPAL, PLAN, knowledge)
        assert (error.value.status, error.value.code) == (
            (503, "C1-QY-054") if outcome.endswith("error") else (409, "C1-QY-051")
        )
        if outcome.endswith("error"):
            assert error.value.__cause__ is primary
        knowledge.assert_awaited_once()
        head.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["error", "mismatch"])
def test_final_workflow_failure_rejects_publication(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        primary = RuntimeError("last workflow read unavailable")
        head = AsyncMock(side_effect=["head1", primary if outcome == "error" else "head2"])
        monkeypatch.setattr(journal, "head", head)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize_after(PRINCIPAL, PLAN, AsyncMock())
        assert (error.value.status, error.value.code) == (
            (503, "C1-QY-054") if outcome == "error" else (409, "C1-QY-051")
        )
        if outcome == "error":
            assert error.value.__cause__ is primary
        assert head.await_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_cancel_and_deadline_during_knowledge_wait_await_all_three_owned_tasks(
    monkeypatch: pytest.MonkeyPatch, external_cancel: bool
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        names = ("knowledge", "authorization", "initial_head")
        started = {name: asyncio.Event() for name in names}
        finished: set[str] = set()

        async def blocked(name: str) -> None:
            started[name].set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def knowledge() -> None:
            await blocked("knowledge")

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            await blocked("authorization")
            raise AssertionError("unreachable")

        async def head() -> str:
            await blocked("initial_head")
            raise AssertionError("unreachable")

        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        task = asyncio.create_task(
            selected.finalize_after(
                PRINCIPAL,
                PLAN,
                knowledge,
                deadline=time.monotonic() + (1 if external_cancel else 0.03),
            )
        )
        await asyncio.gather(*(event.wait() for event in started.values()))
        if external_cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            # The document caller owns pending knowledge timeout semantics.
            with pytest.raises(TimeoutError):
                await task
        assert finished == set(names)

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["initial_head", "authorization", "final_head"])
def test_deadline_after_knowledge_success_maps_query_timeout_and_awaits_cleanup(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        knowledge_done, phase_started = asyncio.Event(), asyncio.Event()
        finished: set[str] = set()
        heads = 0

        async def blocked(name: str) -> None:
            phase_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def knowledge() -> None:
            knowledge_done.set()

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            await knowledge_done.wait()
            if phase != "final_head":
                await blocked("authorization")
            return ids

        async def head() -> str:
            nonlocal heads
            heads += 1
            await knowledge_done.wait()
            if (heads == 1 and phase == "initial_head") or (heads == 2 and phase == "final_head"):
                await blocked("head")
            return "head1"

        monkeypatch.setattr(selected, "_authorize", authorize)
        monkeypatch.setattr(journal, "head", head)
        task = asyncio.create_task(
            selected.finalize_after(PRINCIPAL, PLAN, knowledge, deadline=time.monotonic() + 0.03)
        )
        await phase_started.wait()
        with pytest.raises(QueryPlanError) as error:
            await task
        assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished == (
            {"head", "authorization"}
            if phase == "initial_head"
            else {"head"}
            if phase == "final_head"
            else {"authorization"}
        )
        assert heads == (2 if phase == "final_head" else 1)

    asyncio.run(run())
