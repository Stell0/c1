"""Only disconnected GETs retry, inside the original request lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

import httpx
import pytest

from c1.storage.terminus import BackendError, StorageError, Terminus
from tests.unit.m07.test_fetch_authority import storage


def client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> Terminus:
    result = storage()
    # Retain the real configured client's auth, timeout and defaults; replace
    # only its transport with an in-memory handler before any request.
    monkeypatch.setattr(result._client, "_transport", httpx.MockTransport(handler))
    return result


@pytest.mark.parametrize("head", [False, True])
def test_one_retry_uses_identical_get_and_same_configured_client(
    monkeypatch: pytest.MonkeyPatch, head: bool
) -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            assert terminus._client is original_client
            requests.append(request)
            if len(requests) == 1:
                raise httpx.RemoteProtocolError("disconnected", request=request)
            return httpx.Response(
                200, json=[], headers={"TerminusDB-Data-Version": "branch:pinned"}
            )

        terminus = client(monkeypatch, handler)
        original_client = terminus._client
        async with terminus:
            if head:
                assert await terminus.head() == "branch:pinned"
            else:
                response = await terminus._request(
                    "GET",
                    terminus._document_path + "/local/commit/pinned",
                    params={"id": "Entity/one", "as_list": "true"},
                    headers={"TerminusDB-Data-Version": "branch:base"},
                )
                assert response.json() == []
        assert len(requests) == 2
        first, second = requests
        assert first.method == second.method == "GET"
        assert first.url == second.url
        assert first.headers == second.headers
        assert first.headers["authorization"].startswith("Basic ")
        assert first.content == second.content == b""

    asyncio.run(run())


def test_second_protocol_failure_propagates_without_third_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        calls = 0
        final = httpx.RemoteProtocolError("second disconnected read")

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise final
            raise httpx.RemoteProtocolError("first disconnected read", request=request)

        async with client(monkeypatch, handler) as terminus:
            with pytest.raises(httpx.RemoteProtocolError) as error:
                await terminus.head()
            assert error.value is final
        assert calls == 2

    asyncio.run(run())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_non_get_uncertain_outcome_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []
        disconnected = httpx.RemoteProtocolError("uncertain request outcome")

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise disconnected

        async with client(monkeypatch, handler) as terminus:
            with pytest.raises(httpx.RemoteProtocolError) as error:
                await terminus._request(
                    method, "/api/graphql/admin/c1_m07_synthetic", json={"query": "synthetic"}
                )
            assert error.value is disconnected
        assert len(requests) == 1 and requests[0].method == method

    asyncio.run(run())


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
        httpx.PoolTimeout,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.LocalProtocolError,
    ],
)
def test_other_transport_failures_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, error_type: type[httpx.TransportError]
) -> None:
    async def run() -> None:
        calls = 0
        failure = error_type("synthetic failure")

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise failure

        async with client(monkeypatch, handler) as terminus:
            with pytest.raises(error_type) as error:
                await terminus.head()
            assert error.value is failure
        assert calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("valid_json", [False, True])
def test_http_errors_preserve_sanitized_backend_code_without_retry(
    monkeypatch: pytest.MonkeyPatch, valid_json: bool
) -> None:
    async def run() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if valid_json:
                return httpx.Response(503, json={"api:error": {"@type": "api:Unavailable"}})
            return httpx.Response(503, content=b"invalid JSON")

        async with client(monkeypatch, handler) as terminus:
            with pytest.raises(BackendError) as error:
                await terminus.head()
            assert error.value.status_code == 503
            assert error.value.backend_code == ("api:Unavailable" if valid_json else None)
            assert "invalid JSON" not in str(error.value)
        assert calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("invalid", ["json", "shape", "head"])
def test_success_response_validation_errors_never_trigger_extra_retry(
    monkeypatch: pytest.MonkeyPatch, retry: bool, invalid: str
) -> None:
    async def run() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if retry and calls == 1:
                raise httpx.RemoteProtocolError("disconnected", request=request)
            if invalid == "json":
                return httpx.Response(200, content=b"invalid JSON")
            return httpx.Response(200, json={} if invalid == "shape" else [])

        async with client(monkeypatch, handler) as terminus:
            with pytest.raises(ValueError if invalid == "json" else StorageError):
                if invalid == "head":
                    await terminus.head()
                else:
                    await terminus.documents()
        assert calls == (2 if retry else 1)

    asyncio.run(run())


@pytest.mark.parametrize("second", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_caller_deadline_and_cancellation_drain_first_or_second_attempt(
    monkeypatch: pytest.MonkeyPatch, second: bool, cancel: bool
) -> None:
    async def run() -> None:
        started, finished = asyncio.Event(), asyncio.Event()
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if second and calls == 1:
                raise httpx.RemoteProtocolError("disconnected", request=request)
            started.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                await asyncio.sleep(0)
                finished.set()

        async with client(monkeypatch, handler) as terminus:

            async def read() -> str:
                async with asyncio.timeout(1 if cancel else 0.03):
                    return await terminus.head()

            task = asyncio.create_task(read())
            await started.wait()
            if cancel:
                task.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                await task
            assert task.done() and finished.is_set()
        assert calls == (2 if second else 1)

    asyncio.run(run())


def test_read_only_graphql_query_retries_once_but_mutations_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M08 refinement of D21: a GraphQL query POST is a read and may retry once."""

    async def run() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                raise httpx.RemoteProtocolError("disconnected", request=request)
            return httpx.Response(200, json={"data": {}})

        async with client(monkeypatch, handler) as terminus:
            response = await terminus._request(
                "POST", "/api/graphql/admin/c1_m08", json={"query": "query { Entity { _id } }"}
            )
            assert response.json() == {"data": {}}
        assert len(requests) == 2 and requests[0].content == requests[1].content

        writes: list[httpx.Request] = []

        async def refuse(request: httpx.Request) -> httpx.Response:
            writes.append(request)
            raise httpx.RemoteProtocolError("uncertain", request=request)

        for body in (
            {"query": "mutation { x }"},
            {"query": "query { x }", "variables": {}},
            {"query": "{ x }"},
        ):
            writes.clear()
            async with client(monkeypatch, refuse) as terminus:
                with pytest.raises(httpx.RemoteProtocolError):
                    await terminus._request("POST", "/api/graphql/admin/c1_m08", json=body)
            assert len(writes) == 1

    asyncio.run(run())
