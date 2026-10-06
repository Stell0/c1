"""M14b-T04: journal-indexed history equals TerminusDB history (D7, ADR-0026)."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from tests.integration.m04.conftest import (
    create,
    entity_record,
    identifier,
    live_case,
    new_changeset,
    replace,
    reviewed_apply,
    seeded_scope,
)


def _commits(entries: list[dict[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [(e["identifier"], e["timestamp"], e["message"]) for e in entries]


def test_t04_indexed_history_equals_backend_history_and_falls_back() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M14b-T04 history")
            service = case.runtime.changes.history_service
            first = entity_record(identifier("entity"), label="M14b version one")
            v2 = entity_record(first.id, label="M14b version two")
            v3 = entity_record(first.id, label="M14b version three")
            created = await new_changeset(case, [create(first, shared)])
            assert (await reviewed_apply(case, created["id"]))["state"] == "applied"
            rev1 = await case.knowledge.head()
            for version in (v2, v3):
                change = await new_changeset(case, [replace(version)])
                assert (await reviewed_apply(case, change["id"]))["state"] == "applied"
            # A ChangeSet restore is itself an indexed ChangeSet apply.
            restore = await new_changeset(
                case, [replace(first, "Restore version one")], restores_from_revision=rev1
            )
            assert (await reviewed_apply(case, restore["id"]))["state"] == "applied"

            indexed = await service._indexed_history(first.id)
            assert indexed is not None and len(indexed) == 4
            backend: list[dict[str, Any]] = []
            for document_id in service._document_ids(first.id):
                if await case.knowledge.get(document_id) is not None:
                    backend.extend(await case.knowledge.history(document_id))
            assert _commits(indexed) == _commits(backend)

            # The public page is served from the index with the same items.
            page = await case.request(
                "GET", "/v1/history?resource_id=" + quote(first.id, safe=""), actor="bob"
            )
            assert page.status_code == 200, page.text
            assert [item["revision"] for item in page.json()["items"]] == [
                "branch:" + e["identifier"] for e in indexed
            ]
            assert len(page.json()["items"]) == 4

            # A resource written outside ChangeSets uses the backend probes.
            provisioned = entity_record(label="M14b provisioned")
            await case.provision(provisioned, shared)
            assert await service._indexed_history(provisioned.id) is None
            fallback = await case.request(
                "GET", "/v1/history?resource_id=" + quote(provisioned.id, safe=""), actor="bob"
            )
            assert fallback.status_code == 200, fallback.text
            assert len(fallback.json()["items"]) == 1

    asyncio.run(run())
