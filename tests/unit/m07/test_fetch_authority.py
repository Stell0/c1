"""Overlapped authority and authorized-ID reads cannot publish partial results."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

import c1.query.compile as compiler
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry
from c1.model.records import C1
from c1.storage.mapping import record_to_document, storage_id
from c1.storage.schema import _profile_marker, generated_core_schema
from c1.storage.terminus import BackendError, StorageConfig, StorageError, Terminus

BASE = "urn:c1:instance:dev:"
RESOURCE = "urn:test:resource"


def storage() -> Terminus:
    return Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m07_synthetic",
            instance_base=BASE,
        )
    )


def test_record_queries_overlap_but_results_wait_for_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProfileRegistry()
    record = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})

    async def run() -> None:
        authority_started, query_started, release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def installed(
            _storage: Terminus, _registry: ProfileRegistry, *, backend_gate: asyncio.Semaphore
        ) -> None:
            authority_started.set()
            await query_started.wait()
            await release.wait()

        async def graphql(*_args: Any) -> dict[str, NodeRecord]:
            await authority_started.wait()
            query_started.set()
            return {record.id: record}

        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:
            pending = asyncio.create_task(
                compiler.fetch_records(
                    client,
                    registry,
                    [RESOURCE],
                    revision="old",
                    storage_types={RESOURCE: frozenset(record.types)},
                )
            )
            await asyncio.wait_for(query_started.wait(), 1)
            await asyncio.sleep(0)
            assert not pending.done()
            release.set()
            assert await pending == {record.id: record}

    asyncio.run(run())


@pytest.mark.parametrize("fails", ["authority", "query", "timeout"])
def test_any_failure_cancels_and_awaits_other_phase_without_results(
    monkeypatch: pytest.MonkeyPatch,
    fails: str,
) -> None:
    registry = ProfileRegistry()

    async def run() -> None:
        authority_started, query_started = asyncio.Event(), asyncio.Event()
        finished: set[str] = set()

        async def blocked(name: str) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def installed(
            _storage: Terminus, _registry: ProfileRegistry, *, backend_gate: asyncio.Semaphore
        ) -> None:
            authority_started.set()
            if fails == "authority":
                await query_started.wait()
                raise StorageError("C1-ST-006", "authority mismatch")
            await blocked("authority")

        async def graphql(*_args: Any) -> dict[str, NodeRecord]:
            query_started.set()
            if fails == "query":
                await authority_started.wait()
                raise BackendError(503)
            await blocked("query")
            raise AssertionError("unreachable")

        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:
            expected = (
                TimeoutError
                if fails == "timeout"
                else StorageError
                if fails == "authority"
                else BackendError
            )
            with pytest.raises(expected):
                async with asyncio.timeout(0.03 if fails == "timeout" else 1):
                    await compiler.fetch_records(
                        client,
                        registry,
                        [RESOURCE],
                        revision="old",
                        storage_types={RESOURCE: frozenset({C1 + "Entity"})},
                    )
        assert finished == (
            {"query"}
            if fails == "authority"
            else {"authority"}
            if fails == "query"
            else {"authority", "query"}
        )

    asyncio.run(run())


def test_real_authority_reads_queries_and_record_fallback_share_one_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProfileRegistry()
    record = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})
    doc = record_to_document(record, registry, BASE)
    markers = {
        item["@id"]: item
        for item in [
            record_to_document(_profile_marker(registry, name), registry, BASE)
            for name in registry.profiles
        ]
    }
    active = peak = 0
    calls: set[str] = set()

    async def network(kind: str) -> None:
        nonlocal active, peak
        calls.add(kind)
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.002)
        finally:
            active -= 1

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("graph_type") == "schema":
            await network("schema")
            return httpx.Response(200, json=generated_core_schema(registry))
        identifier = request.url.params["id"]
        if identifier in markers:
            await network("marker")
            return httpx.Response(200, json=[markers[identifier]])
        assert identifier == doc["@id"]
        assert request.url.path.endswith("/local/commit/old")
        await network("fallback")
        return httpx.Response(200, json=[doc])

    async def graphql(
        _storage: Terminus,
        _registry: ProfileRegistry,
        definition: ClassDefinition,
        requested: dict[str, set[str]],
        _commit: str,
    ) -> dict[str, NodeRecord]:
        await network("query")
        if definition.iri == C1 + "Entity":
            backend_id = storage_id(record, definition, BASE)
            raise compiler._GraphQLRecordFallback({}, {backend_id: requested[backend_id]})
        return {}

    monkeypatch.setattr(compiler, "_graphql_chunk", graphql)

    async def run() -> None:
        async with storage() as client:
            client._client = httpx.AsyncClient(
                base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
            )
            gate = asyncio.Semaphore(3)
            results = await asyncio.gather(
                *[
                    compiler.fetch_records(
                        client, registry, [RESOURCE], revision="old", backend_gate=gate
                    )
                    for _ in range(3)
                ]
            )
            assert results == [{RESOURCE: record}] * 3
        assert calls == {"schema", "marker", "query", "fallback"}
        assert active == 0 and peak == 3

    asyncio.run(run())
