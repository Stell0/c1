"""M13 fixes for history and historical reads at reference-deployment scale."""

from __future__ import annotations

import asyncio
import json

import httpx

import c1.query.compile as compiler
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import StorageConfig, Terminus

BASE = "urn:c1:instance:dev:"


def _storage(handler: httpx.MockTransport) -> Terminus:
    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m13_synthetic",
            instance_base=BASE,
        )
    )
    storage._client = httpx.AsyncClient(base_url="http://127.0.0.1:16363", transport=handler)
    return storage


def test_class_undeclared_at_an_old_commit_needs_no_per_document_reads() -> None:
    gets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            gets.append(str(request.url))
            return httpx.Response(404, json={})
        name = json.loads(request.content)["query"].split()[2].split("(")[0]
        return httpx.Response(
            200,
            json={
                "errors": [
                    {
                        "message": f'Unknown field "{name}" on type "Query"',
                        "locations": [{"line": 1, "column": 9}],
                    }
                ]
            },
        )

    async def run() -> None:
        storage = _storage(httpx.MockTransport(handler))
        async with storage:
            found = await compiler._fetch_records_content(
                storage,
                ProfileRegistry(),
                ["urn:c1:instance:dev:entity/00000001-0000-4000-8000-000000000000"],
                "old",
                backend_gate=asyncio.Semaphore(4),
                storage_types=None,
            )
        assert found == {}
        assert gets == []

    asyncio.run(run())


def test_other_graphql_errors_keep_the_exact_per_document_fallback() -> None:
    gets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            gets.append(str(request.url))
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"errors": [{"message": "something else"}]})

    async def run() -> None:
        storage = _storage(httpx.MockTransport(handler))
        async with storage:
            await compiler._fetch_records_content(
                storage,
                ProfileRegistry(),
                ["urn:c1:instance:dev:entity/00000001-0000-4000-8000-000000000000"],
                "old",
                backend_gate=asyncio.Semaphore(4),
                storage_types=None,
            )
        assert gets

    asyncio.run(run())
