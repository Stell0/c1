"""A fresh caller head removes one read without weakening publication guards."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from c1.authorization.journal import Journal
from c1.query.index import CurrentBindingIndex, IndexHeadChanged
from c1.query.plan import QueryPlanError
from tests.unit.m07.test_plan_concurrency import (
    PRINCIPAL,
    RESOURCE,
    FGAFake,
    JournalFake,
    planner,
)


def test_cold_plan_defers_enumeration_guard_until_after_fresh_authorization() -> None:
    async def run() -> None:
        journal = JournalFake()
        selected = planner(journal, FGAFake(journal))
        assert (await selected.build(PRINCIPAL)).authorized_ids == (RESOURCE,)
        assert journal.events.count("head") == 2
        assert journal.events.index("head") < journal.events.index("snapshot")
        assert journal.events[-1] == "head"

        class MutatingJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                self.value = "head2"
                return await super().list_many(kinds)

        changed = MutatingJournal()
        fga = FGAFake(changed)
        changed_planner = planner(changed, fga)
        with pytest.raises(QueryPlanError) as error:
            await changed_planner.build(PRINCIPAL)
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")
        assert fga.checks == 1
        assert changed_planner.index._snapshot is None

    asyncio.run(run())


@pytest.mark.parametrize("cached", [False, True])
def test_mutation_while_waiting_for_index_lock_cannot_publish(cached: bool) -> None:
    async def run() -> None:
        journal = JournalFake()
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        if cached:
            await selected.build(PRINCIPAL)
        fga.checks = 0
        journal.events.clear()
        await selected.index._lock.acquire()
        task = asyncio.create_task(selected.build(PRINCIPAL))
        try:
            while "scopes" not in journal.events:
                await asyncio.sleep(0)
            assert journal.events[0] == "head"
            journal.value = "head2"
        finally:
            selected.index._lock.release()
        with pytest.raises(QueryPlanError) as error:
            await task
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")
        assert fga.checks == 1

    asyncio.run(run())


def test_default_snapshot_still_checks_initial_head_for_cold_and_cached_reads() -> None:
    async def run() -> None:
        journal = JournalFake()
        index = CurrentBindingIndex(cast(Journal, journal))
        await index.snapshot("head1")
        assert journal.events.count("head") == 2
        journal.events.clear()
        await index.snapshot("head1")
        assert journal.events == ["head"]
        journal.value = "head2"
        with pytest.raises(IndexHeadChanged):
            await index.snapshot("head1")
        assert index._snapshot is None
        with pytest.raises(IndexHeadChanged):
            await index.snapshot("head1")

    asyncio.run(run())


def test_cached_head_never_caches_fga_decisions_and_finalize_detects_revocation() -> None:
    async def run() -> None:
        journal = JournalFake()
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        plan = await selected.build(PRINCIPAL)
        fga.allow = False
        with pytest.raises(QueryPlanError) as error:
            await selected.finalize(PRINCIPAL, plan)
        assert error.value.code == "C1-QY-051"
        assert (await selected.build(PRINCIPAL)).authorized_ids == ()
        assert fga.checks == 3
        assert journal.events.count("snapshot") == 1

    asyncio.run(run())
