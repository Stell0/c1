"""HTTP contract checks; real database guarantees are tested separately in M01."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from probes.terminus import BackendError, Terminus


def client_with_handler(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    original = httpx.AsyncClient

    def mock_client(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("probes.terminus.httpx.AsyncClient", mock_client)


def test_head_is_read_only_and_write_preserves_message_and_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], headers={"TerminusDB-Data-Version": "branch:abc"})

    client_with_handler(monkeypatch, handler)

    async def scenario() -> None:
        async with Terminus("http://backend", "synthetic-secret", "c1_m01_batch") as db:
            assert await db.head() == "branch:abc"
            assert (
                await db.insert(
                    [{"@type": "Thing", "@id": "Thing/one"}],
                    "changeset=one digest=123",
                    expected_head="branch:abc",
                )
                == "branch:abc"
            )

    asyncio.run(scenario())
    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[0].url.params["count"] == "0"
    assert requests[0].url.params["as_list"] == "true"
    assert requests[1].headers["TerminusDB-Data-Version"] == "branch:abc"
    assert requests[1].url.params["message"] == "changeset=one digest=123"
    assert json.loads(requests[1].content) == [{"@type": "Thing", "@id": "Thing/one"}]


def test_database_lifecycle_rejects_unscoped_names(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client_with_handler(monkeypatch, handler)

    async def scenario() -> None:
        async with Terminus("http://backend", "secret", "c1") as db:
            with pytest.raises(ValueError, match="limited"):
                await db.create()
            with pytest.raises(ValueError, match="limited"):
                await db.drop()

    asyncio.run(scenario())
    assert requests == []


def test_backend_error_retains_status_and_json_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"api:error": {"@type": "api:DataVersionMismatch"}})

    client_with_handler(monkeypatch, handler)

    async def scenario() -> None:
        async with Terminus("http://backend", "synthetic-secret", "c1_m01_stale") as db:
            with pytest.raises(BackendError) as caught:
                await db.insert([], "digest=123", expected_head="branch:old")
            assert caught.value.status_code == 400
            assert caught.value.error["api:error"]["@type"] == "api:DataVersionMismatch"
            assert "synthetic-secret" not in str(caught.value)

    asyncio.run(scenario())


def test_missing_document_uses_list_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    client_with_handler(monkeypatch, handler)

    async def scenario() -> None:
        async with Terminus("http://backend", "secret", "c1_m01_missing") as db:
            assert await db.get("ProbeRecord/absent") is None

    asyncio.run(scenario())
    assert requests[0].url.params["id"] == "ProbeRecord/absent"
    assert requests[0].url.params["as_list"] == "true"
