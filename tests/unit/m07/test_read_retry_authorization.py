"""Recovered storage GETs retain exact heads and fresh publication authority."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager

import httpx
import pytest

from c1.query.plan import QueryPlanError
from c1.storage.terminus import Terminus
from tests.unit.m07.test_fetch_authority import storage
from tests.unit.m07.test_finalize_concurrency import PLAN
from tests.unit.m07.test_plan_concurrency import PRINCIPAL, FGAFake, JournalFake, planner

KNOWLEDGE_HEAD = "branch:knowledge1"


@asynccontextmanager
async def retrying_storage(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> AsyncIterator[Terminus]:
    async with storage() as backend:
        await backend._client.aclose()
        backend._client = httpx.AsyncClient(
            base_url="http://storage.test", transport=httpx.MockTransport(handler), trust_env=False
        )
        yield backend


class ObservedJournal(JournalFake):
    def __init__(self) -> None:
        super().__init__()
        self.initial_read = asyncio.Event()
        self.heads = 0

    async def head(self) -> str:
        self.heads += 1
        value = await super().head()
        self.initial_read.set()
        return value


class ObservedFGA(FGAFake):
    def __init__(self, journal: JournalFake) -> None:
        super().__init__(journal)
        self.decision_read = asyncio.Event()

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        value = await super().batch_check(checks)
        self.decision_read.set()
        return value


def test_recovered_knowledge_get_still_requires_last_workflow_head_after_revocation() -> None:
    async def run() -> None:
        journal = ObservedJournal()
        fga = ObservedFGA(journal)
        selected = planner(journal, fga)
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.method == "GET"
            if len(requests) == 1:
                await journal.initial_read.wait()
                await fga.decision_read.wait()
                # A supported revocation advances workflow state while the
                # resource's knowledge head remains unchanged.
                journal.value = "head2"
                fga.allow = False
                raise httpx.RemoteProtocolError("synthetic disconnect", request=request)
            return httpx.Response(200, json=[], headers={"TerminusDB-Data-Version": KNOWLEDGE_HEAD})

        async with retrying_storage(handler) as backend:
            client = backend._client

            async def knowledge_unchanged() -> None:
                assert await backend.head() == KNOWLEDGE_HEAD

            with pytest.raises(QueryPlanError) as error:
                await selected.finalize_after(PRINCIPAL, PLAN, knowledge_unchanged)
            assert (error.value.status, error.value.code) == (409, "C1-QY-051")
            assert backend._client is client
        assert len(requests) == 2 and requests[0].url == requests[1].url
        assert journal.heads == 2  # Initial captured head passed; final head detected the change.
        assert fga.checks == 1

    asyncio.run(run())


def test_recovered_knowledge_get_with_changed_head_rejects_publication() -> None:
    async def run() -> None:
        journal = ObservedJournal()
        fga = ObservedFGA(journal)
        selected = planner(journal, fga)
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.method == "GET"
            if len(requests) == 1:
                await journal.initial_read.wait()
                await fga.decision_read.wait()
                raise httpx.RemoteProtocolError("synthetic disconnect", request=request)
            return httpx.Response(
                200, json=[], headers={"TerminusDB-Data-Version": "branch:knowledge2"}
            )

        async with retrying_storage(handler) as backend:

            async def knowledge_unchanged() -> None:
                if await backend.head() != KNOWLEDGE_HEAD:
                    raise QueryPlanError(409, "C1-DC-014", "restart_required")

            with pytest.raises(QueryPlanError) as error:
                await selected.finalize_after(PRINCIPAL, PLAN, knowledge_unchanged)
            assert (error.value.status, error.value.code) == (409, "C1-DC-014")
        assert len(requests) == 2 and requests[0].url == requests[1].url
        assert journal.heads == 1  # A failed knowledge precondition cannot reach the final read.
        assert fga.checks == 1

    asyncio.run(run())


def test_recovered_get_cannot_reuse_positive_authorization_from_selection() -> None:
    async def run() -> None:
        journal = JournalFake()
        recovered = asyncio.Event()

        class RevokedFGA(FGAFake):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                if self.checks:
                    await recovered.wait()
                return await super().batch_check(checks)

        fga = RevokedFGA(journal)
        selected = planner(journal, fga)
        plan = await selected.build(PRINCIPAL)
        assert fga.checks == 1 and plan.authorized_ids == PLAN.authorized_ids
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.method == "GET"
            if len(requests) == 1:
                raise httpx.RemoteProtocolError("synthetic disconnect", request=request)
            # The recovered GET returns an unchanged knowledge head. A new
            # publication check must still observe the current denied grant.
            fga.allow = False
            recovered.set()
            return httpx.Response(200, json=[], headers={"TerminusDB-Data-Version": KNOWLEDGE_HEAD})

        async with retrying_storage(handler) as backend:

            async def knowledge_unchanged() -> None:
                assert await backend.head() == KNOWLEDGE_HEAD

            with pytest.raises(QueryPlanError) as error:
                await selected.finalize_after(PRINCIPAL, plan, knowledge_unchanged)
            assert (error.value.status, error.value.code) == (409, "C1-QY-051")
        assert len(requests) == 2 and requests[0].url == requests[1].url
        assert fga.checks == 2 and journal.value == plan.workflow_head

    asyncio.run(run())
