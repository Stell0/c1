"""ID-bounded GraphQL decoding must preserve exact record values."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import httpx
import pytest

from c1.model.profiles import ClassDefinition, ProfileRegistry
from c1.query.compile import _decode, _GraphQLShapeError, _selection, fetch_records
from c1.storage.terminus import StorageConfig, Terminus

BASE = "urn:c1:instance:dev:"
ASSERTION = BASE + "assertion/00000002-0000-4000-8000-000000000000"


def _class(registry: ProfileRegistry, name: str) -> Any:
    return next(item for item in registry.classes.values() if item.storage_name == name)


def test_selection_contains_declared_fields_and_nested_values() -> None:
    registry = ProfileRegistry()
    selection = _selection(_class(registry, "Assertion"))
    assert "object { iri literal { lexical datatype language } }" in selection
    assert "subject" in selection
    assert "_id canonical_iri types" in selection
    assert "value_integer" not in selection


def test_graphql_decoder_rejects_lexical_number() -> None:
    registry = ProfileRegistry()
    definition = _class(registry, "Assertion")
    item: dict[str, Any] = {
        "_id": "terminusdb:///data/Assertion/00000002-0000-4000-8000-000000000000",
        "canonical_iri": ASSERTION,
        "types": [definition.iri],
        **{
            prop.name: None if prop.max_count == 1 else []
            for prop in definition.properties.values()
        },
    }
    item["object"] = {
        "iri": None,
        "literal": {
            "lexical": 42.5000,
            "datatype": "http://www.w3.org/2001/XMLSchema#decimal",
            "language": None,
        },
    }
    with pytest.raises(_GraphQLShapeError):
        _decode(item, definition, registry, BASE)


def test_empty_input_never_calls_backend() -> None:
    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m02_synthetic",
            instance_base=BASE,
        )
    )

    async def run() -> None:
        try:
            assert await fetch_records(storage, ProfileRegistry(), []) == {}
        finally:
            await storage._client.aclose()

    asyncio.run(run())


def test_document_page_is_bounded_and_revision_pinned() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"@id": "Entity/one"}])

    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m02_synthetic",
            instance_base=BASE,
        )
    )
    storage._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
    )

    async def run() -> None:
        async with storage:
            for skip, count in [(-1, 1), (0, 0), (0, 201), (True, 1), (0, True)]:
                with pytest.raises(ValueError):
                    await storage.documents_page(skip=skip, count=count)
            assert await storage.documents_page(skip=20, count=10, commit="branch:old") == [
                {"@id": "Entity/one"}
            ]

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].url.path == "/api/document/admin/c1_m02_synthetic/local/commit/old"
    assert dict(requests[0].url.params) == {
        "as_list": "true",
        "graph_type": "instance",
        "skip": "20",
        "count": "10",
    }


def test_graphql_chunks_have_global_bounded_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    compile_module = importlib.import_module("c1.query.compile")
    registry = ProfileRegistry()
    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m02_synthetic",
            instance_base=BASE,
        )
    )
    active = 0
    peak = 0
    calls = 0

    async def installed(
        _storage: Terminus,
        _registry: ProfileRegistry,
        *,
        backend_gate: asyncio.Semaphore | None = None,
    ) -> None:
        return None

    async def graphql(
        _storage: Terminus,
        _registry: ProfileRegistry,
        _definition: ClassDefinition,
        requested: dict[str, set[str]],
        _commit_id: str,
    ) -> dict[str, Any]:
        nonlocal active, peak, calls
        assert requested
        active += 1
        peak = max(peak, active)
        calls += 1
        await asyncio.sleep(0.002)
        active -= 1
        return {}

    monkeypatch.setattr(compile_module, "assert_installed_profiles", installed)
    monkeypatch.setattr(compile_module, "_graphql_chunk", graphql)

    async def run() -> None:
        try:
            ids = [
                "urn:c1:instance:dev:entity/00000001-0000-4000-8000-000000000000",
                ASSERTION,
            ]
            assert await fetch_records(storage, registry, ids, revision="branch:old") == {}
        finally:
            await storage._client.aclose()

    asyncio.run(run())
    assert calls > 8
    assert 1 < peak <= 8
