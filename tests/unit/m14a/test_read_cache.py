"""M14a B1: commit-keyed content cache and complete class hints."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

import c1.query.compile as compiler
from c1.authorization.models import Operation
from c1.model.profiles import ProfileRegistry
from c1.query.index import _class_hints
from c1.storage.cache import RecordCache, registry_key
from c1.storage.terminus import StorageConfig, Terminus

BASE = "urn:c1:instance:dev:"
ENTITY = "urn:c1:instance:dev:entity/00000001-0000-4000-8000-000000000000"
C1 = "urn:c1:ns:core#"


def _storage(transport: httpx.MockTransport) -> Terminus:
    storage = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m14a_synthetic",
            instance_base=BASE,
        )
    )
    storage._client = httpx.AsyncClient(base_url="http://127.0.0.1:16363", transport=transport)
    return storage


def _counting_handler(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        name = json.loads(request.content)["query"].split()[2].split("(")[0]
        return httpx.Response(200, json={"data": {name: []}})

    return httpx.MockTransport(handler)


def _fetch(storage: Terminus, commit: str, hints: dict[str, frozenset[str]] | None) -> Any:
    return compiler._fetch_records_content(
        storage,
        ProfileRegistry(),
        [ENTITY],
        commit,
        backend_gate=asyncio.Semaphore(4),
        storage_types=hints,
    )


def test_absence_and_content_are_cached_per_commit_and_hint() -> None:
    calls: list[str] = []

    async def run() -> None:
        storage = _storage(_counting_handler(calls))
        async with storage:
            assert await _fetch(storage, "commit1", None) == {}
            first = len(calls)
            assert first > 0
            assert await _fetch(storage, "commit1", None) == {}
            assert len(calls) == first  # same commit: no backend call
            await _fetch(storage, "commit2", None)
            assert len(calls) > first  # a new commit is a new key
            before_hint = len(calls)
            await _fetch(storage, "commit1", {ENTITY: frozenset({C1 + "Entity"})})
            assert 0 < len(calls) - before_hint < first  # hinted probe: its own key, fewer classes

    asyncio.run(run())


def test_record_cache_is_bounded() -> None:
    cache = RecordCache(max_entries=3)
    for n in range(5):
        cache.put(("c", (), str(n), None), None)
    assert len(cache) == 3
    assert registry_key(ProfileRegistry()) == registry_key(ProfileRegistry())


def test_class_hints_cover_every_class_written_by_applied_operations() -> None:
    def operation(state: str, kind: str, payload: dict[str, Any]) -> Operation:
        return Operation.model_validate(
            {
                "id": "op",
                "kind": kind,
                "actor": "user:x",
                "target": "t",
                "state": state,
                "targets": [],
                "payload": payload,
                "created": "2026-10-05T00:00:00Z",
                "updated": "2026-10-05T00:00:00Z",
            }
        )

    record = {"id": ENTITY, "types": [C1 + "Entity"], "properties": {}}
    retyped = {"id": ENTITY, "types": ["urn:c1:ns:batteries#Product"], "properties": {}}
    hints = _class_hints(
        [
            operation("applied", "changeset_apply", {"records": [record]}),
            operation("applied", "probe_revision", {"record": retyped}),
            operation("pending", "changeset_apply", {"records": [{**record, "id": "other"}]}),
        ]
    )
    assert hints == {ENTITY: frozenset({C1 + "Entity", "urn:c1:ns:batteries#Product"})}
