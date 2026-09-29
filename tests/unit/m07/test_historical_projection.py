"""Historical revisions use the ordinary authorization projection separately."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

import c1.query.service as query_module
from c1.model.nodes import NodeRecord
from c1.model.records import C1, AssertionRecord
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import QueryService
from tests.unit.m07.test_entities_concurrency import service

BASE = "urn:c1:instance:test:"
SUBJECT = BASE + "entity/subject"
TARGET = BASE + "entity/target"
ASSERTION = BASE + "assertion/claim"
BOUNDARY = BASE + "boundary/withheld"
INTERVAL = BASE + "interval/partial"
TIME = "http://www.w3.org/2006/time#"


def test_each_snapshot_has_its_own_visibility_fixed_point_and_hidden_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        monkeypatch.setattr(query.runtime.settings, "instance_base", BASE, raising=False)
        subject = NodeRecord(id=SUBJECT, types=[C1 + "Entity"], properties={})
        target = NodeRecord(id=TARGET, types=[C1 + "Entity"], properties={})
        assertion = AssertionRecord(
            id=ASSERTION,
            subject=SUBJECT,
            predicate="urn:test:relation",
            object=TARGET,
            origin="manual",
        ).to_node()
        interval = NodeRecord(
            id=INTERVAL, types=[C1 + "TimeInterval"], properties={TIME + "hasBeginning": [BOUNDARY]}
        )
        old = {node.id: node for node in (subject, target, assertion, interval)}
        new = {node.id: node for node in (subject, assertion, interval)}
        snapshots = {"old": old, "new": new}
        plan = AuthorizedPlan("security", frozenset(), tuple(old), {})
        cohort = AsyncMock(return_value=snapshots)
        monkeypatch.setattr(query_module, "fetch_record_snapshots", cohort)
        result = await query.historical_records(
            plan,
            ["old", "new"],
            deadline=time.monotonic() + 1,
            backend_gate=asyncio.Semaphore(8),
        )
        assert ASSERTION in result["old"] and ASSERTION not in result["new"]
        assert (
            result["old"].hidden_bounds
            == result["new"].hidden_bounds
            == {INTERVAL: frozenset({TIME + "hasBeginning"})}
        )
        assert TIME + "hasBeginning" not in result["old"][INTERVAL].properties
        # Ordinary records retains its mandatory fetch and identical projection.
        monkeypatch.setattr(query, "records", QueryService.records.__get__(query, QueryService))
        ordinary_fetch = AsyncMock()
        monkeypatch.setattr(query_module, "fetch_records", ordinary_fetch)
        for revision in ("old", "new"):
            ordinary_fetch.return_value = snapshots[revision]
            ordinary = await query.records(plan, revision, deadline=time.monotonic() + 1)
            assert ordinary == result[revision]
            assert ordinary.hidden_bounds == result[revision].hidden_bounds
        assert ordinary_fetch.await_count == 2 and cohort.await_count == 1

    asyncio.run(run())


def test_unrequested_identity_in_one_snapshot_rejects_entire_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        monkeypatch.setattr(query.runtime.settings, "instance_base", BASE, raising=False)
        subject = NodeRecord(id=SUBJECT, types=[C1 + "Entity"], properties={})
        target = NodeRecord(id=TARGET, types=[C1 + "Entity"], properties={})
        plan = AuthorizedPlan("security", frozenset(), (SUBJECT,), {})
        monkeypatch.setattr(
            query_module,
            "fetch_record_snapshots",
            AsyncMock(
                return_value={
                    "old": {SUBJECT: subject},
                    "new": {TARGET: target},
                }
            ),
        )
        with pytest.raises(QueryPlanError) as error:
            await query.historical_records(
                plan,
                ["old", "new"],
                deadline=time.monotonic() + 1,
                backend_gate=asyncio.Semaphore(8),
            )
        assert error.value.code == "C1-QY-054"
        assert error.value.reason == "unexpected_backend_selection"

    asyncio.run(run())


def test_cohort_timeout_maps_to_same_error_after_complete_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = service(monkeypatch)
        finished = asyncio.Event()

        async def blocked(*args: object, **kwargs: object) -> dict[str, dict[str, NodeRecord]]:
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                await asyncio.sleep(0)
                finished.set()

        monkeypatch.setattr(query_module, "fetch_record_snapshots", blocked)
        with pytest.raises(QueryPlanError) as error:
            await query.historical_records(
                AuthorizedPlan("security", frozenset(), (), {}),
                ["old", "new"],
                deadline=time.monotonic() + 0.03,
                backend_gate=asyncio.Semaphore(8),
            )
        assert (error.value.status, error.value.code) == (503, "C1-QY-053")
        assert finished.is_set()

    asyncio.run(run())


def test_registry_replacement_during_cohort_uses_captured_reference_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        from c1.model.profiles import ProfileRegistry, PropertyDefinition

        query = service(monkeypatch)
        monkeypatch.setattr(query.runtime.settings, "instance_base", BASE, raising=False)
        original = query.runtime.registry
        relation = "urn:test:declared-reference"
        withheld = "urn:test:withheld-target"
        original.predicates[relation] = PropertyDefinition(
            name="declared_reference", ranges=(C1 + "Entity",)
        )
        subject = NodeRecord(id=SUBJECT, types=[C1 + "Entity"], properties={relation: [withheld]})
        assertion = AssertionRecord(
            id=ASSERTION, subject=SUBJECT, predicate=relation, object=withheld, origin="manual"
        ).to_node()
        plan = AuthorizedPlan("security", frozenset(), (SUBJECT, ASSERTION), {})
        started, release = asyncio.Event(), asyncio.Event()

        async def cohort(
            storage: object,
            registry: ProfileRegistry,
            ids: object,
            revisions: list[str],
            **kwargs: object,
        ) -> dict[str, dict[str, NodeRecord]]:
            assert registry is original
            started.set()
            await release.wait()
            return {revision: {SUBJECT: subject, ASSERTION: assertion} for revision in revisions}

        monkeypatch.setattr(query_module, "fetch_record_snapshots", cohort)
        task = asyncio.create_task(
            query.historical_records(
                plan,
                ["old", "new"],
                deadline=time.monotonic() + 1,
                backend_gate=asyncio.Semaphore(8),
            )
        )
        await started.wait()
        # The replacement lacks the old predicate declaration. Rereading it
        # would retain this withheld IRI and its relationship assertion.
        query.runtime.registry = ProfileRegistry()
        release.set()
        result = await task
        assert set(result) == {"old", "new"}
        for snapshot in result.values():
            assert set(snapshot) == {SUBJECT}
            assert relation not in snapshot[SUBJECT].properties
        assert query.runtime.registry is not original

    asyncio.run(run())
