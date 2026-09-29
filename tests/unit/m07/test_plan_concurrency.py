"""Concurrent authority reads retain exact-head and fresh permission checks."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

import pytest

from c1.authorization.audit import Audit
from c1.authorization.fga import FGA, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.query.index import IndexHeadChanged
from c1.query.plan import AuthorizedSelection, QueryPlanError

PRINCIPAL = Principal("c1-dev", "dave", "human")
RESOURCE = "urn:test:resource"


class JournalFake:
    def __init__(self) -> None:
        self.value = "head1"
        self.events: list[str] = []
        self.rows: dict[str, list[dict[str, Any]]] = {
            "Scope": [{"id": "shared", "label": "Shared", "state": "active"}],
            "Binding": [
                {
                    "resource_id": RESOURCE,
                    "scope_id": "shared",
                    "state": "active",
                    "operation_id": "op1",
                }
            ],
            "Operation": [],
            "ChangeSet": [],
        }

    async def head(self) -> str:
        self.events.append("head")
        return self.value

    async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
        self.events.append("snapshot")
        return {kind: self.rows[kind] for kind in kinds}


class FGAFake:
    def __init__(self, journal: JournalFake) -> None:
        self.journal = journal
        self.checks = 0
        self.allow = True

    async def list_objects(self, _user: str, _relation: str, _kind: str) -> list[str]:
        self.journal.events.append("scopes")
        return [scope_object("shared")]

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        self.journal.events.append("check")
        self.checks += len(checks)
        assert checks == [(PRINCIPAL.id, "can_read", resource_object(RESOURCE))]
        return [self.allow]

    async def bindings(self, _resource: str) -> list[str]:
        return [scope_object("shared")]


def planner(journal: JournalFake, fga: FGAFake) -> AuthorizedSelection:
    typed_journal, typed_fga = cast(Journal, journal), cast(FGA, fga)
    plane = AuthorizationPlane(typed_journal, typed_fga, "synthetic", Audit())
    return AuthorizedSelection(typed_journal, typed_fga, plane)


def test_scopes_and_snapshot_overlap_only_after_initial_head() -> None:
    async def run() -> None:
        journal = JournalFake()
        scopes_started, snapshot_started = asyncio.Event(), asyncio.Event()

        class ConcurrentFGA(FGAFake):
            async def list_objects(self, user: str, relation: str, kind: str) -> list[str]:
                assert journal.events[0] == "head"
                scopes_started.set()
                await snapshot_started.wait()
                return await super().list_objects(user, relation, kind)

        class ConcurrentJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                assert self.events[0] == "head"
                snapshot_started.set()
                await scopes_started.wait()
                return await super().list_many(kinds)

        journal = ConcurrentJournal()
        fga = ConcurrentFGA(journal)
        plan = await planner(journal, fga).build(PRINCIPAL, deadline=time.monotonic() + 1)
        assert plan.authorized_ids == (RESOURCE,)
        assert fga.checks == 1
        assert journal.events.index("check") > journal.events.index("scopes")
        assert journal.events.index("check") > journal.events.index("snapshot")
        assert journal.events[-1] == "head"

    asyncio.run(run())


@pytest.mark.parametrize("fails", ["scopes", "snapshot", "head_changed"])
def test_one_failed_authority_read_cancels_and_awaits_the_other(fails: str) -> None:
    async def run() -> None:
        started, finished = asyncio.Event(), asyncio.Event()

        async def blocked() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        class FailingJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if fails == "scopes":
                    await blocked()
                    raise AssertionError("unreachable")
                await started.wait()
                if fails == "head_changed":
                    self.value = "head2"
                    raise IndexHeadChanged("changed during failed enumeration")
                raise RuntimeError("unavailable")

        class FailingFGA(FGAFake):
            async def list_objects(self, user: str, relation: str, kind: str) -> list[str]:
                if fails == "scopes":
                    await started.wait()
                    raise RuntimeError("unavailable")
                await blocked()
                raise AssertionError("unreachable")

        journal = FailingJournal()
        fga = FailingFGA(journal)
        with pytest.raises(QueryPlanError) as error:
            await planner(journal, fga).build(PRINCIPAL)
        assert error.value.status == (409 if fails == "head_changed" else 503)
        assert finished.is_set() and fga.checks == 0

    asyncio.run(run())


def test_request_deadline_cancels_and_awaits_both_parallel_reads() -> None:
    async def run() -> None:
        finished: set[str] = set()

        async def blocked(name: str) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        class BlockingJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                await blocked("snapshot")
                raise AssertionError("unreachable")

        class BlockingFGA(FGAFake):
            async def list_objects(self, user: str, relation: str, kind: str) -> list[str]:
                await blocked("scopes")
                raise AssertionError("unreachable")

        journal = BlockingJournal()
        fga = BlockingFGA(journal)
        with pytest.raises(QueryPlanError) as error:
            await planner(journal, fga).build(PRINCIPAL, deadline=time.monotonic() + 0.03)
        assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished == {"scopes", "snapshot"} and fga.checks == 0

    asyncio.run(run())


def test_overlap_keeps_fresh_checks_on_cached_snapshot_and_final_head_change() -> None:
    async def run() -> None:
        journal = JournalFake()
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        assert (await selected.build(PRINCIPAL)).authorized_ids == (RESOURCE,)
        fga.allow = False
        assert (await selected.build(PRINCIPAL)).authorized_ids == ()
        assert fga.checks == 2
        assert journal.events.count("snapshot") == 1

        class FlippingFGA(FGAFake):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                journal.value = "head2"
                return await super().batch_check(checks)

        with pytest.raises(QueryPlanError) as error:
            await planner(journal, FlippingFGA(journal)).build(PRINCIPAL)
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")

    asyncio.run(run())
