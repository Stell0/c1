"""First-cohort prefetch is fresh, bound, single-use, and fully awaited."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

import c1.query.compile as compiler
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry, PropertyDefinition
from c1.model.records import C1
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import QueryService
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, generated_classes, generated_core_schema
from c1.storage.terminus import StorageError
from tests.unit.m07.test_entities_concurrency import service
from tests.unit.m07.test_fetch_authority import BASE, RESOURCE, storage

PLAN = AuthorizedPlan("security", frozenset(), (RESOURCE,), {})
NODE = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})


def query_service(monkeypatch: pytest.MonkeyPatch) -> QueryService:
    query = service(monkeypatch)
    monkeypatch.setattr(query.runtime.settings, "instance_base", "urn:test:", raising=False)
    return query


def test_preparation_is_new_single_use_and_later_cohort_still_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        authority = AsyncMock()
        content = AsyncMock(return_value={RESOURCE: NODE})
        monkeypatch.setattr(compiler, "assert_installed_profiles", authority)
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        deadline, gate = time.monotonic() + 1, asyncio.Semaphore(8)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        await asyncio.sleep(0)
        assert authority.await_count == 1
        await compiler.fetch_records(
            query.runtime.knowledge,
            query.runtime.registry,
            PLAN.authorized_ids,
            revision="current",
            backend_gate=gate,
        )
        assert authority.await_count == 2  # Never initial-fetch authority reuse.
        await query.historical_records(
            PLAN, ["old", "new"], deadline=deadline, backend_gate=gate, preparation=preparation
        )
        assert authority.await_count == 2
        with pytest.raises(QueryPlanError):
            await query.historical_records(
                PLAN, ["later"], deadline=deadline, backend_gate=gate, preparation=preparation
            )
        await query.historical_records(PLAN, ["later"], deadline=deadline, backend_gate=gate)
        assert authority.await_count == 3
        await preparation.close()
        await preparation.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad", [["same", "same"], ["old", "branch:old"], list(map(str, range(9))), ["bad/revision"]]
)
def test_invalid_or_empty_cohort_does_not_consume_preparation(
    monkeypatch: pytest.MonkeyPatch, bad: list[str]
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        monkeypatch.setattr(compiler, "assert_installed_profiles", AsyncMock())
        content = AsyncMock(return_value={RESOURCE: NODE})
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        deadline, gate = time.monotonic() + 1, asyncio.Semaphore(8)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        try:
            with pytest.raises(ValueError):
                await query.historical_records(
                    PLAN, bad, deadline=deadline, backend_gate=gate, preparation=preparation
                )
            assert (
                await query.historical_records(
                    PLAN, [], deadline=deadline, backend_gate=gate, preparation=preparation
                )
                == {}
            )
            assert content.await_count == 0
            assert await query.historical_records(
                PLAN, ["old"], deadline=deadline, backend_gate=gate, preparation=preparation
            )
        finally:
            await preparation.close()

    asyncio.run(run())


@pytest.mark.parametrize("mismatch", ["plan", "storage", "gate", "deadline", "closed"])
def test_mismatched_preparation_fails_closed_before_content(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        monkeypatch.setattr(compiler, "assert_installed_profiles", AsyncMock())
        content = AsyncMock(return_value={RESOURCE: NODE})
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        deadline, gate = time.monotonic() + 1, asyncio.Semaphore(8)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        selected = PLAN
        if mismatch == "plan":
            selected = AuthorizedPlan(PLAN.workflow_head, frozenset(), PLAN.authorized_ids, {})
        elif mismatch == "storage":
            query.runtime.knowledge = storage()
        elif mismatch == "gate":
            gate = asyncio.Semaphore(8)
        elif mismatch == "deadline":
            deadline += 1
        else:
            await preparation.close()
        try:
            with pytest.raises(QueryPlanError) as error:
                await query.historical_records(
                    selected, ["old"], deadline=deadline, backend_gate=gate, preparation=preparation
                )
            assert error.value.reason == "historical_preparation_mismatch"
            assert content.await_count == 0
        finally:
            await preparation.close()

    asyncio.run(run())


def test_registry_replacement_uses_one_captured_proof_for_decode_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        monkeypatch.setattr(query.runtime.settings, "instance_base", "urn:test:", raising=False)
        registry = query.runtime.registry
        relation = "urn:test:reference"
        registry.predicates[relation] = PropertyDefinition(
            name="reference", ranges=(C1 + "Entity",)
        )
        node = NODE.model_copy(update={"properties": {relation: ["urn:test:hidden"]}})
        authority_started, release = asyncio.Event(), asyncio.Event()

        async def authority(_storage: object, proof: ProfileRegistry, **kwargs: object) -> None:
            assert proof is registry
            authority_started.set()
            await release.wait()

        async def content(
            _storage: object, proof: ProfileRegistry, *args: object, **kwargs: object
        ) -> dict[str, NodeRecord]:
            assert proof is registry
            return {RESOURCE: node}

        monkeypatch.setattr(compiler, "assert_installed_profiles", authority)
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        deadline, gate = time.monotonic() + 1, asyncio.Semaphore(8)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        await authority_started.wait()
        query.runtime.registry = ProfileRegistry()
        release.set()
        try:
            result = await query.historical_records(
                PLAN, ["old", "new"], deadline=deadline, backend_gate=gate, preparation=preparation
            )
            assert all(relation not in records[RESOURCE].properties for records in result.values())
            with pytest.raises(ValueError):
                preparation._validate(
                    query.runtime.knowledge,
                    query.runtime.registry,
                    gate,
                    PLAN,
                    PLAN.workflow_head,
                    deadline,
                )
        finally:
            await preparation.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome", ["success", "authority", "content", "cancel", "close", "timeout"]
)
def test_prepared_cohort_waits_for_all_and_cleans_every_owned_task(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        authority_started, all_content, release_authority, release_content = (
            asyncio.Event() for _ in range(4)
        )
        started: set[str] = set()
        finished: set[str] = set()
        gate = asyncio.Semaphore(8)

        async def authority(
            _storage: object, _registry: object, *, backend_gate: asyncio.Semaphore
        ) -> None:
            assert backend_gate is gate
            authority_started.set()
            try:
                await release_authority.wait()
                if outcome == "authority":
                    raise StorageError("C1-ST-006", "missing profile")
            finally:
                await asyncio.sleep(0)
                finished.add("authority")

        async def content(
            _storage: object, _registry: object, _ids: object, commit: str, **kwargs: Any
        ) -> dict[str, NodeRecord]:
            assert kwargs["backend_gate"] is gate
            started.add(commit)
            if started == {"old", "new"}:
                all_content.set()
            try:
                await release_content.wait()
                if outcome == "content" and commit == "old":
                    raise StorageError("C1-ST-005", "collision")
                return {RESOURCE: NODE}
            finally:
                await asyncio.sleep(0)
                finished.add(commit)

        monkeypatch.setattr(compiler, "assert_installed_profiles", authority)
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        deadline = time.monotonic() + (0.04 if outcome == "timeout" else 1)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        await authority_started.wait()
        task = asyncio.create_task(
            query.historical_records(
                PLAN, ["old", "new"], deadline=deadline, backend_gate=gate, preparation=preparation
            )
        )
        await all_content.wait()
        assert not task.done()
        if outcome == "success":
            release_authority.set()
            await asyncio.sleep(0)
            assert not task.done()
            release_content.set()
            assert await task
        elif outcome in {"authority", "content"}:
            (release_authority if outcome == "authority" else release_content).set()
            with pytest.raises(StorageError):
                await task
        elif outcome in {"cancel", "close"}:
            if outcome == "cancel":
                task.cancel()
            else:
                await preparation.close()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(QueryPlanError) as error:
                await task
            assert error.value.code == "C1-QY-053"
        await preparation.close()
        assert finished == {"authority", "old", "new"}

    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_actual_prepared_check_reads_schema_and_every_marker_with_shared_gate(
    monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        registry = query.runtime.registry
        for name in ("topics", "batteries"):
            registry.load(Path("tests/fixtures/profiles") / name)
        schema = generated_core_schema(registry)
        for name in registry.profiles:
            if name != "core":
                schema.extend(generated_classes(registry, name))
        markers = {
            item["@id"]: item
            for item in (
                record_to_document(_profile_marker(registry, name), registry, BASE)
                for name in registry.profiles
            )
        }
        active = maximum = schema_reads = 0
        marker_reads: set[str] = set()
        gate = asyncio.Semaphore(8)

        async def network() -> None:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.001)
            finally:
                active -= 1

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal schema_reads
            await network()
            if request.url.params.get("graph_type") == "schema":
                schema_reads += 1
                return httpx.Response(200, json=schema)
            identifier = request.url.params["id"]
            marker_reads.add(identifier)
            return httpx.Response(200, json=[] if missing else [markers[identifier]])

        async def content(*args: object, **kwargs: Any) -> dict[str, NodeRecord]:
            assert args[1] is registry and kwargs["backend_gate"] is gate
            async with gate:
                await network()
            return {RESOURCE: NODE}

        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        async with storage() as client:
            client._client = httpx.AsyncClient(
                base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
            )
            query.runtime.knowledge = client
            deadline = time.monotonic() + 1
            preparation = query.prepare_historical_records(
                PLAN, deadline=deadline, backend_gate=gate
            )
            try:
                cohort = query.historical_records(
                    PLAN,
                    list(map(str, range(8))),
                    deadline=deadline,
                    backend_gate=gate,
                    preparation=preparation,
                )
                if missing:
                    with pytest.raises(StorageError) as error:
                        await cohort
                    assert error.value.code == "C1-ST-006"
                else:
                    assert len(await cohort) == 8
            finally:
                await preparation.close()
        assert schema_reads == 1
        assert marker_reads == set(markers)
        assert active == 0 and maximum == 8

    asyncio.run(run())


def test_expired_deadline_and_arbitrary_task_cannot_authorize_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        authority = AsyncMock()
        monkeypatch.setattr(compiler, "assert_installed_profiles", authority)
        gate = asyncio.Semaphore(8)
        with pytest.raises(QueryPlanError):
            query.prepare_historical_records(PLAN, deadline=time.monotonic() - 1, backend_gate=gate)
        task = asyncio.create_task(asyncio.sleep(0))
        try:
            with pytest.raises(QueryPlanError):
                await query.historical_records(
                    PLAN,
                    ["old"],
                    deadline=time.monotonic() + 1,
                    backend_gate=gate,
                    preparation=cast(compiler._HistoricalPreparation, task),
                )
        finally:
            await task
        assert authority.await_count == 0

    asyncio.run(run())


def test_cancel_before_collector_first_turn_still_drains_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        query = query_service(monkeypatch)
        started, finished = asyncio.Event(), asyncio.Event()

        async def authority(*args: Any, **kwargs: Any) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        original = compiler._collect_record_snapshots

        def cancel_collector(
            *args: Any, **kwargs: Any
        ) -> Coroutine[Any, Any, dict[str, dict[str, NodeRecord]]]:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            return original(*args, **kwargs)

        content = AsyncMock()
        monkeypatch.setattr(compiler, "assert_installed_profiles", authority)
        monkeypatch.setattr(compiler, "_fetch_records_content", content)
        monkeypatch.setattr(compiler, "_collect_record_snapshots", cancel_collector)
        deadline, gate = time.monotonic() + 1, asyncio.Semaphore(8)
        preparation = query.prepare_historical_records(PLAN, deadline=deadline, backend_gate=gate)
        await started.wait()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(
                query.historical_records(
                    PLAN, ["old"], deadline=deadline, backend_gate=gate, preparation=preparation
                )
            )
        assert finished.is_set()
        assert content.await_count == 0
        await preparation.close()

    asyncio.run(run())
