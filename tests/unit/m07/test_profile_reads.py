"""Every fresh profile authority read remains exact, bounded and fail closed."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from typing import Any

import httpx
import pytest

from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, assert_installed_profiles, generated_core_schema
from c1.storage.terminus import BackendError, StorageConfig, StorageError, Terminus

BASE = "urn:c1:instance:dev:"


def fixtures() -> tuple[ProfileRegistry, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    registry = ProfileRegistry()
    for index in range(10):
        name = f"synthetic{index}"
        registry.profiles[name] = replace(registry.profiles["core"], name=name, classes={})
    schema = generated_core_schema(registry)
    markers = [
        record_to_document(_profile_marker(registry, name), registry, BASE)
        for name in registry.profiles
    ]
    return registry, schema, {marker["@id"]: marker for marker in markers}


def storage(handler: Any) -> Terminus:
    client = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m07_synthetic",
            instance_base=BASE,
        )
    )
    client._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.parametrize("shared", [False, True])
def test_fresh_schema_and_markers_share_global_network_bound(shared: bool) -> None:
    registry, schema, markers = fixtures()
    active = peak = schema_reads = marker_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, schema_reads, marker_reads
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.002)
            if request.url.params.get("graph_type") == "schema":
                schema_reads += 1
                return httpx.Response(200, json=schema)
            marker_reads += 1
            return httpx.Response(200, json=[markers[request.url.params["id"]]])
        finally:
            active -= 1

    async def run() -> None:
        async with storage(handler) as client:
            if shared:
                gate = asyncio.Semaphore(3)
                await asyncio.gather(
                    *[
                        assert_installed_profiles(client, registry, backend_gate=gate)
                        for _ in range(3)
                    ]
                )
            else:
                await assert_installed_profiles(client, registry)
                await assert_installed_profiles(client, registry)

    asyncio.run(run())
    assert active == 0 and peak == (3 if shared else 8)
    assert schema_reads == (3 if shared else 2)
    assert marker_reads == len(markers) * schema_reads


@pytest.mark.parametrize("failure", ["missing_marker", "changed_marker", "changed_schema"])
def test_any_incomplete_or_mismatched_authority_fails_closed(failure: str) -> None:
    registry, schema, markers = fixtures()
    changed_schema = copy.deepcopy(schema[:-1] if failure == "changed_schema" else schema)
    first_marker = next(iter(markers))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("graph_type") == "schema":
            return httpx.Response(200, json=changed_schema)
        identifier = request.url.params["id"]
        if failure == "missing_marker" and identifier == first_marker:
            return httpx.Response(200, json=[])
        marker = copy.deepcopy(markers[identifier])
        if failure == "changed_marker" and identifier == first_marker:
            marker["profileVersion"]["lexical"] = "99.0.0"
        return httpx.Response(200, json=[marker])

    async def run() -> None:
        async with storage(handler) as client:
            with pytest.raises(StorageError) as error:
                await assert_installed_profiles(client, registry)
            assert error.value.code == "C1-ST-006"

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [False, True])
def test_failure_or_timeout_cancels_and_awaits_sibling_authority_reads(timeout: bool) -> None:
    registry, _, _ = fixtures()
    active = started = finished = 0

    async def run() -> None:
        marker_started = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active, started, finished
            active += 1
            started += 1
            try:
                if not timeout and request.url.params.get("graph_type") == "schema":
                    await marker_started.wait()
                    return httpx.Response(503, json={})
                marker_started.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                active -= 1
                finished += 1
            raise AssertionError("unreachable")

        async with storage(handler) as client:
            if timeout:
                with pytest.raises(TimeoutError):
                    async with asyncio.timeout(0.03):
                        await assert_installed_profiles(
                            client, registry, backend_gate=asyncio.Semaphore(2)
                        )
            else:
                with pytest.raises(BackendError):
                    await assert_installed_profiles(
                        client, registry, backend_gate=asyncio.Semaphore(2)
                    )
        assert active == 0 and started == finished and started >= 2

    asyncio.run(run())


def test_marker_revocation_between_calls_cannot_reuse_success() -> None:
    registry, schema, markers = fixtures()
    available = True

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("graph_type") == "schema":
            return httpx.Response(200, json=schema)
        return httpx.Response(200, json=[markers[request.url.params["id"]]] if available else [])

    async def run() -> None:
        nonlocal available
        async with storage(handler) as client:
            await assert_installed_profiles(client, registry)
            available = False
            with pytest.raises(StorageError, match="profile marker is missing"):
                await assert_installed_profiles(client, registry)

    asyncio.run(run())
