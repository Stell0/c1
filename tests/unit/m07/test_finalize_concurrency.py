"""Overlapped final authorization retains exact-head precedence and cleanup."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

import pytest

from c1.authorization.principal import Principal
from c1.query.plan import AuthorizedPlan, QueryPlanError
from tests.unit.m07.test_plan_concurrency import (
    PRINCIPAL,
    RESOURCE,
    FGAFake,
    JournalFake,
    planner,
)

PLAN = AuthorizedPlan("head1", frozenset({"shared"}), (RESOURCE,), {RESOURCE: "shared"})


def test_final_authorization_overlaps_first_head_and_waits_for_final_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        first_started, auth_started, final_started = (asyncio.Event() for _ in range(3))
        release_first, release_final = asyncio.Event(), asyncio.Event()
        heads = 0

        async def head() -> str:
            nonlocal heads
            heads += 1
            if heads == 1:
                first_started.set()
                await auth_started.wait()
                await release_first.wait()
            else:
                final_started.set()
                await release_final.wait()
            return "head1"

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            assert (principal, ids, scope_by_id) == (
                PRINCIPAL,
                PLAN.authorized_ids,
                PLAN.scope_by_id,
            )
            auth_started.set()
            await first_started.wait()
            await release_first.wait()
            return ids

        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        task = asyncio.create_task(selected.finalize(PRINCIPAL, PLAN))
        await auth_started.wait()
        await first_started.wait()
        assert not task.done()
        release_first.set()
        await final_started.wait()
        assert not task.done()
        release_final.set()
        await task
        assert heads == 2

    asyncio.run(run())


@pytest.mark.parametrize("head_failure", ["mismatch", "unavailable"])
def test_first_head_error_takes_precedence_over_completed_authorization_failure(
    monkeypatch: pytest.MonkeyPatch, head_failure: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        auth_finished = asyncio.Event()
        primary = RuntimeError("head unavailable")

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            try:
                raise RuntimeError("authorization unavailable")
            finally:
                auth_finished.set()

        async def head() -> str:
            await auth_finished.wait()
            if head_failure == "unavailable":
                raise primary
            return "head2"

        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize(PRINCIPAL, PLAN)
        assert auth_finished.is_set()
        assert (error.value.status, error.value.code) == (
            (409, "C1-QY-051") if head_failure == "mismatch" else (503, "C1-QY-054")
        )
        if head_failure == "unavailable":
            assert error.value.__cause__ is primary

    asyncio.run(run())


@pytest.mark.parametrize("first_result", ["head2", "error"])
def test_first_head_error_cancels_and_awaits_running_authorization(
    monkeypatch: pytest.MonkeyPatch, first_result: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        auth_started, auth_finished = asyncio.Event(), asyncio.Event()

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            auth_started.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                await asyncio.sleep(0)
                auth_finished.set()

        async def head() -> str:
            await auth_started.wait()
            if first_result == "error":
                raise RuntimeError("head unavailable")
            return first_result

        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize(PRINCIPAL, PLAN)
        assert auth_finished.is_set()
        assert error.value.code == ("C1-QY-054" if first_result == "error" else "C1-QY-051")

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["failure", "denial", "head_mutation"])
def test_authorization_failure_denial_and_final_head_change_never_publish(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        heads = 0
        auth_finished = asyncio.Event()
        failure = RuntimeError("authorization unavailable")

        async def head() -> str:
            nonlocal heads
            heads += 1
            return "head2" if heads == 2 else "head1"

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            try:
                if outcome == "failure":
                    raise failure
                return () if outcome == "denial" else ids
            finally:
                auth_finished.set()

        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize(PRINCIPAL, PLAN)
        assert auth_finished.is_set()
        assert heads == (2 if outcome == "head_mutation" else 1)
        assert error.value.code == ("C1-QY-054" if outcome == "failure" else "C1-QY-051")
        if outcome == "failure":
            assert error.value.__cause__ is failure

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["first_head", "authorization", "final_head"])
@pytest.mark.parametrize("external_cancel", [False, True])
def test_deadline_and_external_cancel_clean_up_each_phase(
    monkeypatch: pytest.MonkeyPatch, phase: str, external_cancel: bool
) -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        auth_started, phase_started = asyncio.Event(), asyncio.Event()
        finished: set[str] = set()
        heads = 0

        async def blocked(name: str) -> None:
            phase_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def head() -> str:
            nonlocal heads
            heads += 1
            await auth_started.wait()
            if (heads == 1 and phase == "first_head") or (heads == 2 and phase == "final_head"):
                await blocked("head")
            return "head1"

        async def authorize(
            principal: Principal, ids: tuple[str, ...], scope_by_id: Mapping[str, str]
        ) -> tuple[str, ...]:
            auth_started.set()
            try:
                if phase != "final_head":
                    if phase == "authorization":
                        phase_started.set()
                    await asyncio.Event().wait()
                return ids
            finally:
                await asyncio.sleep(0)
                finished.add("authorization")

        monkeypatch.setattr(journal, "head", head)
        monkeypatch.setattr(selected, "_authorize", authorize)
        task = asyncio.create_task(
            selected.finalize(
                PRINCIPAL, PLAN, deadline=time.monotonic() + (1 if external_cancel else 0.03)
            )
        )
        await phase_started.wait()
        if external_cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(QueryPlanError) as error:
                await task
            assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished == (
            {"authorization"} if phase == "authorization" else {"head", "authorization"}
        )
        assert heads == (2 if phase == "final_head" else 1)

    asyncio.run(run())
