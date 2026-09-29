"""Unverified candidates stay private until the planner's fresh head barrier."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, cast

import pytest

from c1.authorization.journal import Journal
from c1.query.index import CurrentBindingIndex, IndexHeadChanged, IndexUnavailable
from c1.query.plan import QueryPlanError
from tests.unit.m07.test_plan_concurrency import (
    PRINCIPAL,
    RESOURCE,
    FGAFake,
    JournalFake,
    planner,
)


def test_blocked_authorization_keeps_candidates_private_and_loses_cache_cas() -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        journal = JournalFake()

        class BlockingFGA(FGAFake):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                started.set()
                await release.wait()
                return await super().batch_check(checks)

        selected = planner(journal, BlockingFGA(journal))
        task = asyncio.create_task(selected.build(PRINCIPAL))
        await started.wait()
        assert selected.index._snapshot is None
        # A standalone caller cannot reuse the first caller's unverified rows.
        newer = await selected.index.snapshot("head1")
        assert journal.events.count("snapshot") == 2
        assert selected.index._snapshot is newer
        release.set()
        assert (await task).authorized_ids == (RESOURCE,)
        assert selected.index._snapshot is newer

    asyncio.run(run())


def test_prepare_publish_cas_does_not_overwrite_newer_verified_snapshot() -> None:
    async def run() -> None:
        journal = JournalFake()
        index = CurrentBindingIndex(cast(Journal, journal))
        journal.rows["ChangeSet"] = [{"id": "old", "state": "draft"}]
        old = await index._prepare_after_head("head1")
        assert index._snapshot is None
        journal.value = "head2"
        journal.rows["ChangeSet"] = [{"id": "new", "state": "draft"}]
        newer = await index.snapshot("head2")
        index._publish_verified(old)
        assert index._snapshot is newer
        assert newer.history_manifest is not None
        assert json.loads(newer.history_manifest)["ChangeSet"] == journal.rows["ChangeSet"]
        # Invalidations also advance the CAS token, even when the cache is empty.
        pending = await index._prepare_after_head("head2")
        journal.value = "head3"
        with pytest.raises(IndexHeadChanged):
            await index.snapshot("head2")
        index._publish_verified(pending)
        assert index._snapshot is None

    asyncio.run(run())


def test_plan_manifest_is_canonical_immutable_copy_from_the_same_enumeration() -> None:
    async def run() -> None:
        class ManifestJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                assert kinds == {"Scope", "Binding", "Operation", "ChangeSet"}
                return await super().list_many(kinds)

        journal = ManifestJournal()
        # ChangeSet payloads retain envelope-compatible legacy/draft shapes;
        # index preparation does not globally validate ChangeSet models.
        journal.rows["ChangeSet"] = [{"legacy": {"items": [{"label": "révision"}]}}]
        journal.rows["Operation"] = [
            {
                "id": "applied",
                "kind": "changeset_apply",
                "actor": "producer",
                "target": "proposal",
                "state": "applied",
                "created": "now",
                "updated": "now",
                "payload": {"records": [{"id": RESOURCE, "types": ["urn:type:Entity"]}]},
            }
        ]
        original = {"ChangeSet": journal.rows["ChangeSet"], "Operation": journal.rows["Operation"]}
        expected = json.dumps(
            original, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        first = await selected.build(PRINCIPAL)
        assert first.history_manifest == expected
        assert selected.index._snapshot is not None
        assert selected.index._snapshot.history_manifest is first.history_manifest
        assert journal.events == ["head", "scopes", "snapshot", "check", "head"]
        journal.rows["ChangeSet"][0]["legacy"]["items"][0]["label"] = "changed"
        journal.rows["Operation"][0]["payload"]["records"][0]["types"].append("urn:type:Other")
        decoded = json.loads(expected)
        decoded["Operation"].clear()
        assert first.history_manifest == expected
        cached = await selected.build(PRINCIPAL)
        assert cached.history_manifest is first.history_manifest
        assert journal.events.count("snapshot") == 1
        assert fga.checks == 2
        journal.value = "head2"
        changed = await selected.build(PRINCIPAL)
        assert changed.history_manifest != expected
        assert journal.events.count("snapshot") == 2
        assert fga.checks == 3

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["initial_head", "enumeration", "post_head"])
@pytest.mark.parametrize("outcome", ["success", "failure", "mismatch", "cancel"])
def test_ordinary_read_cannot_replace_or_clear_concurrent_verified_publication(
    phase: str, outcome: str
) -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        unavailable = RuntimeError("unavailable")

        class ControlledJournal(JournalFake):
            controlled = False
            heads = 0

            async def pause(self) -> None:
                started.set()
                await release.wait()
                if outcome == "failure":
                    raise unavailable

            async def head(self) -> str:
                if self.controlled:
                    self.heads += 1
                    if (phase == "initial_head" and self.heads == 1) or (
                        phase == "post_head" and self.heads == 2
                    ):
                        await self.pause()
                return await super().head()

            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if self.controlled and phase == "enumeration":
                    await self.pause()
                return await super().list_many(kinds)

        journal = ControlledJournal()
        index = CurrentBindingIndex(cast(Journal, journal))
        journal.value = "head0"
        old_cache = await index.snapshot("head0")
        journal.value = "head1"
        prepared = await index._prepare_after_head("head1")
        journal.controlled = True
        task = asyncio.create_task(index.snapshot("head1"))
        await started.wait()
        assert index._snapshot is old_cache
        # The private caller completes its own exact-head barrier while the
        # ordinary caller owns the lock and awaits a backend read.
        assert await journal.head() == "head1"
        index._publish_verified(prepared)
        assert index._snapshot is prepared.snapshot
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            if outcome == "mismatch":
                journal.value = "head2"
            release.set()
            if outcome == "failure":
                with pytest.raises(IndexUnavailable) as error:
                    await task
                assert error.value.__cause__ is unavailable
            elif outcome == "mismatch":
                with pytest.raises(IndexHeadChanged):
                    await task
            else:
                result = await task
                assert result.head == "head1"
                assert (result is prepared.snapshot) == (phase == "initial_head")
        assert index._snapshot is prepared.snapshot

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_prepare_does_not_clear_another_verified_publication(cancel: bool) -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        class FailingJournal(JournalFake):
            fail = False

            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if self.fail:
                    started.set()
                    await release.wait()
                    raise RuntimeError("unavailable")
                return await super().list_many(kinds)

        journal = FailingJournal()
        index = CurrentBindingIndex(cast(Journal, journal))
        verified = await index._prepare_after_head("head1")
        journal.fail = True
        task = asyncio.create_task(index._prepare_after_head("head2"))
        await started.wait()
        index._publish_verified(verified)
        if cancel:
            task.cancel()
        else:
            release.set()
        with pytest.raises(asyncio.CancelledError if cancel else IndexUnavailable):
            await task
        assert index._snapshot is verified.snapshot

    asyncio.run(run())


def test_standalone_after_head_keeps_its_cold_guard_and_cache_behavior() -> None:
    async def run() -> None:
        journal = JournalFake()
        index = CurrentBindingIndex(cast(Journal, journal))
        snapshot = await index._snapshot_after_head("head1")
        assert journal.events == ["snapshot", "head"]
        assert index._snapshot is snapshot
        journal.events.clear()
        assert await index._snapshot_after_head("head1") is snapshot
        assert journal.events == []

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["enumeration", "authorization", "head"])
@pytest.mark.parametrize("cancel", [False, True])
def test_incomplete_plan_cancels_and_awaits_without_cache_publication(
    phase: str, cancel: bool
) -> None:
    async def run() -> None:
        started, finished = asyncio.Event(), asyncio.Event()

        async def blocked() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        class BlockingJournal(JournalFake):
            heads = 0

            async def head(self) -> str:
                self.heads += 1
                if phase == "head" and self.heads == 2:
                    await blocked()
                return await super().head()

            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if phase == "enumeration":
                    await blocked()
                return await super().list_many(kinds)

        class BlockingFGA(FGAFake):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                if phase == "authorization":
                    await blocked()
                return await super().batch_check(checks)

        journal = BlockingJournal()
        selected = planner(journal, BlockingFGA(journal))
        task = asyncio.create_task(
            selected.build(PRINCIPAL, deadline=time.monotonic() + (1 if cancel else 0.03))
        )
        await started.wait()
        assert selected.index._snapshot is None
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(QueryPlanError) as error:
                await task
            assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished.is_set()
        assert selected.index._snapshot is None

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["authorization", "head"])
def test_failed_authorization_or_post_head_does_not_publish(phase: str) -> None:
    async def run() -> None:
        class FailingJournal(JournalFake):
            heads = 0

            async def head(self) -> str:
                self.heads += 1
                if phase == "head" and self.heads == 2:
                    raise RuntimeError("unavailable")
                return await super().head()

        class FailingFGA(FGAFake):
            async def bindings(self, resource: str) -> list[str]:
                if phase == "authorization":
                    raise RuntimeError("unavailable")
                return await super().bindings(resource)

        journal = FailingJournal()
        selected = planner(journal, FailingFGA(journal))
        with pytest.raises(QueryPlanError) as error:
            await selected.build(PRINCIPAL)
        assert (error.value.status, error.value.code) == (503, "C1-QY-054")
        assert selected.index._snapshot is None

    asyncio.run(run())


def test_authorization_mutation_cannot_publish_or_install_cache() -> None:
    async def run() -> None:
        journal = JournalFake()

        class MutatingFGA(FGAFake):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                self.journal.value = "head2"
                return await super().batch_check(checks)

        selected = planner(journal, MutatingFGA(journal))
        with pytest.raises(QueryPlanError) as error:
            await selected.build(PRINCIPAL)
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")
        assert selected.index._snapshot is None

    asyncio.run(run())


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("failure", ["scopes", "candidates", "pending", "duplicate", "invalid"])
def test_candidate_errors_keep_head_priority_and_do_not_launch_fga(
    changed: bool, failure: str
) -> None:
    async def run() -> None:
        class CandidateJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if changed:
                    self.value = "head2"
                return await super().list_many(kinds)

        journal = CandidateJournal()
        fga = FGAFake(journal)
        selected = planner(journal, fga)
        if failure == "scopes":
            selected.max_readable_scopes = 1
        elif failure == "candidates":
            selected.candidate_limit = 1
            journal.rows["Binding"].append(
                {**journal.rows["Binding"][0], "resource_id": "urn:test:other"}
            )
        elif failure == "pending":
            operation: dict[str, Any] = {
                "id": "install",
                "kind": "changeset_apply",
                "actor": "installer",
                "target": "profile",
                "state": "pending",
                "created": "now",
                "updated": "now",
                "payload": {"profile_alias": "topics"},
            }
            journal.rows["Operation"].append(operation)
        elif failure == "duplicate":
            journal.rows["Binding"].append(dict(journal.rows["Binding"][0]))
        else:
            journal.rows["Scope"][0]["state"] = "unsupported"
        with pytest.raises(QueryPlanError) as error:
            await selected.build(PRINCIPAL)
        expected = (
            (409, "C1-QY-051")
            if changed
            else (422, "C1-QY-050")
            if failure == "scopes"
            else (422, "C1-QY-052")
            if failure == "candidates"
            else (503, "C1-QY-054")
        )
        assert (error.value.status, error.value.code) == expected
        assert fga.checks == 0
        assert selected.index._snapshot is None
        assert journal.events.count("head") == 2

    asyncio.run(run())


@pytest.mark.parametrize("changed", [False, True])
def test_simultaneous_structural_and_scope_failures_keep_restart_priority(changed: bool) -> None:
    async def run() -> None:
        class FailingJournal(JournalFake):
            async def list_many(self, kinds: set[str]) -> dict[str, list[dict[str, Any]]]:
                if changed:
                    self.value = "head2"
                self.rows["Binding"].append(dict(self.rows["Binding"][0]))
                return await super().list_many(kinds)

        class FailingFGA(FGAFake):
            async def list_objects(self, user: str, relation: str, kind: str) -> list[str]:
                raise RuntimeError("unavailable")

        journal = FailingJournal()
        selected = planner(journal, FailingFGA(journal))
        with pytest.raises(QueryPlanError) as error:
            await selected.build(PRINCIPAL)
        assert (error.value.status, error.value.code) == (
            (409, "C1-QY-051") if changed else (503, "C1-QY-054")
        )
        assert selected.index._snapshot is None

    asyncio.run(run())
