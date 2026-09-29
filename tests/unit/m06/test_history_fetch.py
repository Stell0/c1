"""Historical snapshot probes preserve type coverage and shared read bounds."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry
from c1.query.compile import _GraphQLShapeError, fetch_records
from c1.storage.mapping import storage_id
from c1.storage.terminus import BackendError, StorageConfig, Terminus

BASE = "urn:c1:instance:dev:"
CORE = "urn:c1:ns:core#"
RESOURCE = "urn:c1:test:historical-resource"
OTHER = "urn:c1:test:other-resource"


def _storage() -> Terminus:
    return Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m06_synthetic",
            instance_base=BASE,
        )
    )


async def _installed(
    _storage: Terminus,
    _registry: ProfileRegistry,
    *,
    backend_gate: asyncio.Semaphore | None = None,
) -> None:
    return None


def test_complete_type_union_finds_both_sides_of_historical_class_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("c1.query.compile")
    registry = ProfileRegistry()
    calls: list[tuple[str, str]] = []

    async def graphql(
        _storage: Terminus,
        _registry: ProfileRegistry,
        definition: ClassDefinition,
        requested: dict[str, set[str]],
        commit_id: str,
    ) -> dict[str, NodeRecord]:
        calls.append((commit_id, definition.storage_name))
        assert {identifier for ids in requested.values() for identifier in ids} == {RESOURCE}
        expected_class = "Document" if commit_id == "old" else "DocumentPart"
        if definition.storage_name != expected_class:
            return {}
        record = NodeRecord(id=RESOURCE, types=[definition.iri], properties={})
        return {RESOURCE: record}

    monkeypatch.setattr(module, "assert_installed_profiles", _installed)
    monkeypatch.setattr(module, "_graphql_chunk", graphql)

    async def run() -> None:
        storage = _storage()
        try:
            hints = {RESOURCE: frozenset({CORE + "Document", CORE + "DocumentPart"})}
            old = await fetch_records(
                storage, registry, [RESOURCE], revision="branch:old", storage_types=hints
            )
            new = await fetch_records(
                storage, registry, [RESOURCE], revision="branch:new", storage_types=hints
            )
            assert old[RESOURCE].types == [CORE + "Document"]
            assert new[RESOURCE].types == [CORE + "DocumentPart"]
        finally:
            await storage._client.aclose()

    asyncio.run(run())
    assert set(calls) == {
        (revision, name) for revision in ("old", "new") for name in ("Document", "DocumentPart")
    }


@pytest.mark.parametrize(
    "hint",
    [
        None,
        frozenset(),
        frozenset({"urn:c1:unknown:class"}),
        frozenset({CORE + "DocumentPart", "urn:c1:unknown:class"}),
    ],
)
def test_missing_empty_and_unknown_per_id_hints_preserve_all_classes(
    monkeypatch: pytest.MonkeyPatch,
    hint: frozenset[str] | None,
) -> None:
    module = importlib.import_module("c1.query.compile")
    registry = ProfileRegistry()
    probes: dict[str, set[str]] = {RESOURCE: set(), OTHER: set()}

    async def graphql(
        _storage: Terminus,
        _registry: ProfileRegistry,
        definition: ClassDefinition,
        requested: dict[str, set[str]],
        _commit_id: str,
    ) -> dict[str, NodeRecord]:
        for identifiers in requested.values():
            for identifier in identifiers:
                probes[identifier].add(definition.iri)
        return {}

    monkeypatch.setattr(module, "assert_installed_profiles", _installed)
    monkeypatch.setattr(module, "_graphql_chunk", graphql)

    async def run() -> None:
        storage = _storage()
        try:
            hints = {RESOURCE: frozenset({CORE + "DocumentPart"})}
            if hint is not None:
                hints[OTHER] = hint
            assert (
                await fetch_records(
                    storage, registry, [RESOURCE, OTHER], revision="branch:old", storage_types=hints
                )
                == {}
            )
        finally:
            await storage._client.aclose()

    asyncio.run(run())
    assert probes[RESOURCE] == {CORE + "DocumentPart"}
    assert probes[OTHER] == set(registry.classes)


def test_shared_gate_bounds_all_network_reads_across_concurrent_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("c1.query.compile")
    registry = ProfileRegistry()
    active = 0
    peak = 0
    calls = {"profiles": 0, "graphql": 0, "get": 0}

    async def network(kind: str) -> None:
        nonlocal active, peak
        calls[kind] += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.001)
        finally:
            active -= 1

    async def installed(
        _storage: Terminus,
        _registry: ProfileRegistry,
        *,
        backend_gate: asyncio.Semaphore | None = None,
    ) -> None:
        assert backend_gate is not None
        async with backend_gate:
            await network("profiles")

    async def graphql(*_args: Any) -> dict[str, NodeRecord]:
        await network("graphql")
        raise _GraphQLShapeError

    async def get(_backend_id: str, *, commit: str) -> None:
        assert commit in {"old", "new", "third", "fourth"}
        await network("get")
        return None

    monkeypatch.setattr(module, "assert_installed_profiles", installed)
    monkeypatch.setattr(module, "_graphql_chunk", graphql)

    async def run() -> None:
        storage = _storage()
        monkeypatch.setattr(storage, "get", get)
        try:
            ids = [RESOURCE, OTHER, "urn:c1:test:third-resource"]
            hints = {identifier: frozenset({CORE + "DocumentPart"}) for identifier in ids}
            gate = asyncio.Semaphore(3)
            snapshots = await asyncio.gather(
                *[
                    fetch_records(
                        storage,
                        registry,
                        ids,
                        revision="branch:" + revision,
                        backend_gate=gate,
                        storage_types=hints,
                    )
                    for revision in ("old", "new", "third", "fourth")
                ]
            )
            assert snapshots == [{}, {}, {}, {}]
        finally:
            await storage._client.aclose()

    asyncio.run(run())
    assert peak == 3 and active == 0
    assert calls == {"profiles": 4, "graphql": 4, "get": 12}


@pytest.mark.parametrize("fallback", [False, True])
def test_backend_failure_cancels_and_awaits_sibling_reads(
    monkeypatch: pytest.MonkeyPatch,
    fallback: bool,
) -> None:
    module = importlib.import_module("c1.query.compile")
    registry = ProfileRegistry()
    monkeypatch.setattr(module, "assert_installed_profiles", _installed)

    async def run() -> None:
        storage = _storage()
        sibling_started = asyncio.Event()
        sibling_finished = asyncio.Event()
        cancelled = False

        async def blocked_sibling() -> None:
            nonlocal cancelled
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                # A finished marker after suspension proves gather awaited
                # cancellation cleanup, rather than only calling cancel().
                await asyncio.sleep(0)
                sibling_finished.set()

        async def graphql(
            _storage: Terminus,
            _registry: ProfileRegistry,
            definition: ClassDefinition,
            _requested: dict[str, set[str]],
            _commit_id: str,
        ) -> dict[str, NodeRecord]:
            if fallback:
                raise _GraphQLShapeError
            if definition.storage_name == "Document":
                await sibling_started.wait()
                raise BackendError(503)
            await blocked_sibling()
            return {}

        definition = registry.classes[CORE + "DocumentPart"]
        fail_id = storage_id(
            NodeRecord(id=RESOURCE, types=[definition.iri], properties={}), definition, BASE
        )

        async def get(backend_id: str, *, commit: str) -> None:
            assert commit == "old"
            if backend_id == fail_id:
                await sibling_started.wait()
                raise BackendError(503)
            await blocked_sibling()
            return None

        monkeypatch.setattr(module, "_graphql_chunk", graphql)
        monkeypatch.setattr(storage, "get", get)
        try:
            ids = [RESOURCE, OTHER] if fallback else [RESOURCE]
            types = (
                {CORE + "DocumentPart"} if fallback else {CORE + "Document", CORE + "DocumentPart"}
            )
            with pytest.raises(BackendError):
                await asyncio.wait_for(
                    fetch_records(
                        storage,
                        registry,
                        ids,
                        revision="branch:old",
                        backend_gate=asyncio.Semaphore(2),
                        storage_types={identifier: frozenset(types) for identifier in ids},
                    ),
                    timeout=1,
                )
            assert cancelled and sibling_finished.is_set()
        finally:
            await storage._client.aclose()

    asyncio.run(run())
