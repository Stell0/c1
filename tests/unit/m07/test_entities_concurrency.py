"""Only unpinned entity requests overlap revision and current authorization."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.principal import Principal
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.query.filters import QueryFilters, filter_digest
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords, QueryService
from c1.runtime import Runtime

PRINCIPAL = Principal("test", "alice", "human")
PLAN = AuthorizedPlan("security-head", frozenset(), (), {})


def service(monkeypatch: pytest.MonkeyPatch, *, budget: int = 2000) -> QueryService:
    settings = SimpleNamespace(
        cursor_secret="x" * 32,
        query_candidate_limit=5000,
        max_readable_scopes=500,
        query_time_budget_ms=budget,
        instance_id="test",
    )
    runtime = cast(
        Runtime,
        SimpleNamespace(
            settings=settings,
            journal=None,
            fga=None,
            plane=None,
            knowledge=SimpleNamespace(head=AsyncMock(return_value="revision")),
            registry=ProfileRegistry(),
        ),
    )
    result = QueryService(runtime)
    monkeypatch.setattr(result, "selection", AsyncMock(return_value=(PLAN, {})))
    monkeypatch.setattr(result, "records", AsyncMock(return_value=AuthorizedRecords({}, {})))
    monkeypatch.setattr(result.planner, "finalize", AsyncMock())
    return result


@pytest.mark.parametrize("waiting", ["head", "selection"])
def test_head_and_selection_overlap_but_retrieval_waits_for_both(
    monkeypatch: pytest.MonkeyPatch,
    waiting: str,
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        head_started, selection_started, release = (asyncio.Event() for _ in range(3))

        async def head() -> str:
            head_started.set()
            await selection_started.wait()
            if waiting == "head":
                await release.wait()
            return "revision"

        async def selection(
            *args: object, **kwargs: object
        ) -> tuple[AuthorizedPlan, dict[str, NodeRecord]]:
            selection_started.set()
            await head_started.wait()
            if waiting == "selection":
                await release.wait()
            return PLAN, {}

        monkeypatch.setattr(query.runtime.knowledge, "head", head)
        monkeypatch.setattr(query, "selection", selection)
        task = asyncio.create_task(query.entities(PRINCIPAL, QueryFilters()))
        await head_started.wait()
        await selection_started.wait()
        await asyncio.sleep(0)
        cast(AsyncMock, query.records).assert_not_awaited()
        release.set()
        assert (await task)["revision"] == "revision"
        cast(AsyncMock, query.records).assert_awaited_once()
        record_call = cast(AsyncMock, query.records).await_args
        assert record_call is not None and record_call.args == (PLAN, "revision")
        cast(AsyncMock, query.planner.finalize).assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("fails", ["head", "selection"])
def test_original_failure_cancels_and_awaits_sibling_without_retrieval(
    monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        started, finished = asyncio.Event(), asyncio.Event()
        failure = QueryPlanError(409, "C1-QY-051", "restart_required")

        async def one(name: str) -> None:
            if name == fails:
                await started.wait()
                raise failure
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        async def head() -> str:
            await one("head")
            raise AssertionError("unreachable")

        async def selection(
            *args: object, **kwargs: object
        ) -> tuple[AuthorizedPlan, dict[str, NodeRecord]]:
            await one("selection")
            raise AssertionError("unreachable")

        monkeypatch.setattr(query.runtime.knowledge, "head", head)
        monkeypatch.setattr(query, "selection", selection)
        with pytest.raises(QueryPlanError) as error:
            await query.entities(PRINCIPAL, QueryFilters())
        assert error.value is failure and finished.is_set()
        cast(AsyncMock, query.records).assert_not_awaited()
        cast(AsyncMock, query.planner.finalize).assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_timeout_or_cancellation_cleans_up_both_reads(
    monkeypatch: pytest.MonkeyPatch, external_cancel: bool
) -> None:
    async def run() -> None:
        query = service(monkeypatch, budget=30 if not external_cancel else 2000)
        started: set[str] = set()
        finished: set[str] = set()

        async def one(name: str) -> None:
            started.add(name)
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def head() -> str:
            await one("head")
            raise AssertionError("unreachable")

        async def selection(
            *args: object, **kwargs: object
        ) -> tuple[AuthorizedPlan, dict[str, NodeRecord]]:
            await one("selection")
            raise AssertionError("unreachable")

        monkeypatch.setattr(query.runtime.knowledge, "head", head)
        monkeypatch.setattr(query, "selection", selection)
        task = asyncio.create_task(query.entities(PRINCIPAL, QueryFilters()))
        if external_cancel:
            while len(started) != 2:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(QueryPlanError) as error:
                await task
            assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished == {"head", "selection"}
        cast(AsyncMock, query.records).assert_not_awaited()

    asyncio.run(run())


def test_invalid_cursor_fails_before_authorization_or_head_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        with pytest.raises(QueryPlanError) as error:
            await query.entities(PRINCIPAL, QueryFilters(cursor="invalid"))
        assert (error.value.status, error.value.code) == (400, "C1-QY-004")
        cast(AsyncMock, query.runtime.knowledge.head).assert_not_awaited()
        cast(AsyncMock, query.selection).assert_not_awaited()
        cast(AsyncMock, query.records).assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("cursor", [False, True])
def test_pinned_revision_and_valid_cursor_remain_sequential(
    monkeypatch: pytest.MonkeyPatch, cursor: bool
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        filters = QueryFilters(revision="pinned")
        if cursor:
            filters = QueryFilters()
            token = query.codec.encode(
                principal=PRINCIPAL.id,
                revision="pinned",
                filter_digest=filter_digest(filters),
                order=filters.order,
                last_key=("last", "id"),
            )
            filters = QueryFilters(cursor=token)
        original = query._revision
        resolved = False

        async def revision(
            filters: QueryFilters, principal: Principal
        ) -> tuple[str, tuple[str, str] | None]:
            nonlocal resolved
            result = await original(filters, principal)
            await asyncio.sleep(0)
            resolved = True
            return result

        async def selection(
            *args: object, **kwargs: object
        ) -> tuple[AuthorizedPlan, dict[str, NodeRecord]]:
            assert resolved
            return PLAN, {}

        monkeypatch.setattr(query, "_revision", revision)
        monkeypatch.setattr(query, "selection", selection)
        assert (await query.entities(PRINCIPAL, filters))["revision"] == "pinned"
        cast(AsyncMock, query.runtime.knowledge.head).assert_not_awaited()
        record_call = cast(AsyncMock, query.records).await_args
        assert record_call is not None and record_call.args == (PLAN, "pinned")

    asyncio.run(run())
