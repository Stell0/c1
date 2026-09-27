"""M04 storage adapter request and validation contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from c1.interchange import import_jsonld
from c1.model.nodes import ValidatedBatch
from c1.model.profiles import ProfileRegistry
from c1.storage import schema
from c1.storage.terminus import StorageConfig, StorageError, Terminus
from tests.integration.m02.conftest import fixture_payload


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> Terminus:
    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic-test-value",
            organization="admin",
            database="c1_m03_storage",
            instance_base="urn:c1:instance:dev:",
        )
    )
    storage._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
    )
    return storage


def test_log_paging_and_history_use_bound_database_paths() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"identifier": "commit_one", "message": "receipt"}])

    async def run() -> None:
        async with _client(handler) as storage:
            assert (await storage.log())[0]["identifier"] == "commit_one"
            assert (await storage.log(start=20, count=20))[0]["message"] == "receipt"
            assert (await storage.history("Entity/item"))[0]["identifier"] == "commit_one"

    asyncio.run(run())
    assert requests[0].url.path == "/api/log/admin/c1_m03_storage"
    assert not requests[0].url.params
    assert dict(requests[1].url.params) == {"start": "20", "count": "20"}
    assert requests[2].url.path == "/api/history/admin/c1_m03_storage"
    assert dict(requests[2].url.params) == {"id": "Entity/item"}


def test_log_rejects_unbounded_or_invalid_page_before_network() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    async def run() -> None:
        async with _client(handler) as storage:
            for kwargs in (
                {"start": -1, "count": 5},
                {"start": 5},
                {"count": 0},
                {"count": 101},
                {"count": True},
            ):
                with pytest.raises(ValueError):
                    await storage.log(**kwargs)
            with pytest.raises(ValueError):
                await storage.history("")

    asyncio.run(run())
    assert requests == []


def test_log_and_history_reject_malformed_backend_lists() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"identifier": "good"}, "bad"])

    async def run() -> None:
        async with _client(handler) as storage:
            with pytest.raises(StorageError, match="C1-ST-003"):
                await storage.log(count=2)
            with pytest.raises(StorageError, match="C1-ST-003"):
                await storage.history("Entity/item")

    asyncio.run(run())


def test_upsert_records_sends_one_receipt_bearing_create_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"TerminusDB-Data-Version": "branch:next"})

    async def installed(_storage: Terminus, _registry: ProfileRegistry) -> None:
        return None

    monkeypatch.setattr(schema, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    batch = import_jsonld(fixture_payload(), registry)
    receipt = json.dumps({"c1": 2, "changeset": "synthetic", "digest": "abc"})

    async def run() -> None:
        async with _client(handler) as storage:
            assert (
                await storage.upsert_records(
                    batch, registry, expected_head="branch:previous", message=receipt
                )
                == "branch:next"
            )

    asyncio.run(run())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PUT"
    assert request.url.path == "/api/document/admin/c1_m03_storage"
    assert request.url.params["create"] == "true"
    assert request.url.params["graph_type"] == "instance"
    assert request.url.params["message"] == receipt
    assert request.headers["TerminusDB-Data-Version"] == "branch:previous"
    assert len(json.loads(request.content)) == len(batch.records)


def test_upsert_rejects_invalid_payload_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    registry = ProfileRegistry()
    batch = import_jsonld(fixture_payload(), registry)
    duplicate = ValidatedBatch(records=[batch.records[0], batch.records[0]])

    async def run() -> None:
        async with _client(handler) as storage:
            with pytest.raises(ValueError, match="message"):
                await storage.upsert_records(
                    batch, registry, expected_head="branch:base", message=""
                )
            with pytest.raises(ValueError, match="C1-IX-030"):
                await storage.upsert_records(
                    duplicate, registry, expected_head="branch:base", message="receipt"
                )

    asyncio.run(run())
    assert requests == []
