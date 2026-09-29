"""A bounded history cohort needs one fresh authority and every exact snapshot."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import c1.query.compile as compiler
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry
from c1.model.records import C1, RDF
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, generated_core_schema
from c1.storage.terminus import StorageError, Terminus
from tests.unit.m07.test_compile_fallback import XSD, assertion, rows_for
from tests.unit.m07.test_fetch_authority import BASE, RESOURCE, storage


def test_cohort_waits_for_every_snapshot_and_new_authority_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        authority_started, snapshots_started, release_authority, release_last = (
            asyncio.Event() for _ in range(4)
        )
        authorities = 0
        seen: set[str] = set()
        node = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})

        async def installed(
            _storage: Terminus, _registry: ProfileRegistry, *, backend_gate: asyncio.Semaphore
        ) -> None:
            nonlocal authorities
            authorities += 1
            authority_started.set()
            await snapshots_started.wait()
            await release_authority.wait()

        async def graphql(
            _storage: Terminus,
            _registry: ProfileRegistry,
            definition: ClassDefinition,
            requested: dict[str, set[str]],
            commit: str,
        ) -> dict[str, NodeRecord]:
            assert definition.iri == C1 + "Entity"
            assert set().union(*requested.values()) == {RESOURCE}
            await authority_started.wait()
            seen.add(commit)
            if seen == {"old", "middle", "new"}:
                snapshots_started.set()
            if commit == "new":
                await release_last.wait()
            return {RESOURCE: node}

        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:

            async def fetch() -> dict[str, dict[str, NodeRecord]]:
                return await compiler.fetch_record_snapshots(
                    client,
                    registry,
                    [RESOURCE],
                    ["branch:old", "middle", "commit:new"],
                    backend_gate=asyncio.Semaphore(8),
                    storage_types={RESOURCE: frozenset(node.types)},
                )

            task = asyncio.create_task(fetch())
            await snapshots_started.wait()
            assert not task.done()
            release_authority.set()
            await asyncio.sleep(0)
            assert not task.done()
            release_last.set()
            assert await task == {
                key: {RESOURCE: node} for key in ("branch:old", "middle", "commit:new")
            }
            await fetch()
            assert authorities == 2  # Request-local cohort, never a positive cache.

    asyncio.run(run())


@pytest.mark.parametrize("revisions", [[str(i) for i in range(9)], ["same", "same"], ["bad/rev"]])
def test_invalid_cohort_is_rejected_before_authority_or_content(
    monkeypatch: pytest.MonkeyPatch, revisions: list[str]
) -> None:
    async def run() -> None:
        installed, graphql = AsyncMock(), AsyncMock()
        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:
            with pytest.raises(ValueError):
                await compiler.fetch_record_snapshots(
                    client,
                    ProfileRegistry(),
                    [RESOURCE],
                    revisions,
                    backend_gate=asyncio.Semaphore(8),
                )
        installed.assert_not_awaited()
        graphql.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("fails", ["authority", "snapshot", "timeout", "cancel"])
def test_cohort_failure_cancels_and_awaits_all_authority_and_snapshot_work(
    monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        started: set[str] = set()
        finished: set[str] = set()
        all_started = asyncio.Event()

        async def one(name: str) -> None:
            started.add(name)
            if started == {"authority", "first", "second"}:
                all_started.set()
            try:
                await all_started.wait()
                if (fails == "authority" and name == "authority") or (
                    fails == "snapshot" and name == "first"
                ):
                    raise StorageError("C1-ST-006", "synthetic failure")
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.add(name)

        async def installed(
            _storage: Terminus, _registry: ProfileRegistry, *, backend_gate: asyncio.Semaphore
        ) -> None:
            await one("authority")

        async def graphql(
            _storage: Terminus,
            _registry: ProfileRegistry,
            definition: ClassDefinition,
            requested: dict[str, set[str]],
            commit: str,
        ) -> dict[str, NodeRecord]:
            await one(commit)
            raise AssertionError("unreachable")

        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:

            async def fetch() -> dict[str, dict[str, NodeRecord]]:
                async with asyncio.timeout(0.03 if fails == "timeout" else 1):
                    return await compiler.fetch_record_snapshots(
                        client,
                        registry,
                        [RESOURCE],
                        ["first", "second"],
                        backend_gate=asyncio.Semaphore(8),
                        storage_types={RESOURCE: frozenset({C1 + "Entity"})},
                    )

            task = asyncio.create_task(fetch())
            if fails == "cancel":
                await all_started.wait()
                task.cancel()
            expected = (
                asyncio.CancelledError
                if fails == "cancel"
                else TimeoutError
                if fails == "timeout"
                else StorageError
            )
            with pytest.raises(expected):
                await task
        assert finished == {"authority", "first", "second"}

    asyncio.run(run())


def test_cohort_preserves_exact_numeric_fallback_and_revision_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProfileRegistry()
    good = assertion("cohort-good", "urn:test:object")
    numeric = assertion("cohort-number", LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
    rows, documents = rows_for([good, numeric], registry)
    rows[1]["object"]["literal"]["lexical"] = 42.5
    reads: list[tuple[str, str]] = []
    installed = AsyncMock()
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)

    def handler(request: httpx.Request) -> httpx.Response:
        commit = request.url.path.rsplit("/", 1)[-1]
        assert commit in {"first", "second"}
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"Assertion": rows}})
        identifier = request.url.params["id"]
        reads.append((commit, identifier))
        return httpx.Response(200, json=[documents[identifier]])

    async def run() -> None:
        from tests.unit.m07.test_compile_fallback import storage as mock_storage

        async with mock_storage(handler) as client:
            result = await compiler.fetch_record_snapshots(
                client,
                registry,
                [good.id, numeric.id],
                ["first", "second"],
                backend_gate=asyncio.Semaphore(8),
                storage_types={node.id: frozenset(node.types) for node in (good, numeric)},
            )
        assert all(snapshot == {good.id: good, numeric.id: numeric} for snapshot in result.values())
        assert all(
            snapshot[numeric.id].properties[RDF + "object"][0]
            == LiteralValue(lexical="42.5000", datatype=XSD + "decimal")
            for snapshot in result.values()
        )
        installed.assert_awaited_once()

    asyncio.run(run())
    numeric_backend = next(
        key for key, doc in documents.items() if doc["canonical_iri"] == numeric.id
    )
    assert sorted(reads) == [("first", numeric_backend), ("second", numeric_backend)]


def test_real_cohort_authority_fallback_and_queries_share_gate_without_hint_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProfileRegistry()
    node = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})
    document = record_to_document(node, registry, BASE)
    markers = {
        item["@id"]: item
        for item in [
            record_to_document(_profile_marker(registry, name), registry, BASE)
            for name in registry.profiles
        ]
    }
    active = maximum = schema_calls = marker_calls = 0
    probes: dict[str, set[str]] = {}

    async def network() -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.001)
        finally:
            active -= 1

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal schema_calls, marker_calls
        await network()
        if request.url.params.get("graph_type") == "schema":
            schema_calls += 1
            return httpx.Response(200, json=generated_core_schema(registry))
        identifier = request.url.params["id"]
        if identifier in markers:
            marker_calls += 1
            return httpx.Response(200, json=[markers[identifier]])
        assert identifier == document["@id"]
        assert request.url.path.rsplit("/", 1)[-1] in {"first", "second", "third"}
        return httpx.Response(200, json=[document])

    async def graphql(
        _storage: Terminus,
        _registry: ProfileRegistry,
        definition: ClassDefinition,
        requested: dict[str, set[str]],
        commit: str,
    ) -> dict[str, NodeRecord]:
        await network()
        probes.setdefault(commit, set()).add(definition.iri)
        if definition.iri == C1 + "Entity":
            raise compiler._GraphQLShapeError
        return {}

    monkeypatch.setattr(compiler, "_graphql_chunk", graphql)

    async def run() -> None:
        async with storage() as client:
            client._client = httpx.AsyncClient(
                base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
            )
            gate = asyncio.Semaphore(3)
            result = await compiler.fetch_record_snapshots(
                client,
                registry,
                [RESOURCE],
                ["first", "second", "third"],
                backend_gate=gate,
                storage_types={RESOURCE: frozenset({"urn:unknown:class"})},
            )
            assert result == {key: {RESOURCE: node} for key in ("first", "second", "third")}
        assert active == 0 and maximum == 3
        assert schema_calls == marker_calls == 1
        assert all(types == set(registry.classes) for types in probes.values())

    asyncio.run(run())


def test_ordinary_fetch_schedules_authority_children_before_content_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        entered: list[str] = []
        registry = ProfileRegistry()

        async def installed(
            _storage: Terminus, _registry: ProfileRegistry, *, backend_gate: asyncio.Semaphore
        ) -> None:
            async def read(name: str) -> None:
                async with backend_gate:
                    entered.append(name)
                    await asyncio.sleep(0)

            await asyncio.gather(read("schema"), read("marker"))

        async def graphql(*_args: object) -> dict[str, NodeRecord]:
            entered.append("content")
            return {}

        monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:
            await compiler.fetch_records(
                client,
                registry,
                [RESOURCE],
                revision="old",
                backend_gate=asyncio.Semaphore(1),
                storage_types={RESOURCE: frozenset({C1 + "Entity"})},
            )
        assert entered == ["schema", "marker", "content"]

    asyncio.run(run())


def test_identity_collision_within_one_revision_rejects_whole_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        node = NodeRecord(id=RESOURCE, types=[C1 + "Entity"], properties={})
        monkeypatch.setattr(compiler, "assert_installed_profiles", AsyncMock())

        async def graphql(
            _storage: Terminus,
            _registry: ProfileRegistry,
            definition: ClassDefinition,
            requested: dict[str, set[str]],
            commit: str,
        ) -> dict[str, NodeRecord]:
            return {RESOURCE: node} if definition.iri in {C1 + "Entity", C1 + "Source"} else {}

        monkeypatch.setattr(compiler, "_graphql_chunk", graphql)
        async with storage() as client:
            with pytest.raises(StorageError) as error:
                await compiler.fetch_record_snapshots(
                    client,
                    registry,
                    [RESOURCE],
                    ["first", "second"],
                    backend_gate=asyncio.Semaphore(8),
                )
        assert error.value.code == "C1-ST-005"

    asyncio.run(run())
