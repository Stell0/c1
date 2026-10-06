"""M14b-T03: the journal record migration on real services (D4, ADR-0026)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from c1.authorization.journal import _RECORD_KINDS, _document_id, _legacy_id
from tests.integration.m04.conftest import (
    create,
    live_case,
    new_changeset,
    new_entity,
    reviewed_apply,
    seeded_scope,
)


def test_t03_legacy_journal_migrates_idempotently_and_keeps_every_payload() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M14b-T03 migration")
            change = await new_changeset(
                case, [create(new_entity("M14b migrated"), shared)], key="m14b-t03"
            )
            applied = await reviewed_apply(case, change["id"])
            assert applied["state"] == "applied"

            # Rewrite the journal into the pre-M14b layout (one class).
            storage = case.journal._storage
            _version, records = await storage.documents_at_version(type="WorkflowRecord")
            assert {r["kind"] for r in records} >= {"ValidationReport", "ApplyReceipt"}
            expected = {(r["kind"], r["key"]): json.loads(r["payload_json"]) for r in records}
            legacy: list[dict[str, Any]] = [
                {**r, "@type": "WorkflowEntry", "@id": _legacy_id(r["kind"], r["key"])}
                for r in records
            ]
            await storage._put(legacy, expected_head=await storage.head(), message="t", create=True)
            await storage._delete(
                [r["@id"] for r in records], expected_head=await storage.head(), message="t"
            )
            case.journal._snapshot = None
            case.journal._view = None
            for kind, key in expected:
                assert await case.journal.get(kind, key) is None

            assert await case.journal.migrate_records() == len(expected)
            assert await case.journal.migrate_records() == 0
            for (kind, key), payload in expected.items():
                assert kind in _RECORD_KINDS
                assert await case.journal.get(kind, key) == payload
                assert await storage.get(_legacy_id(kind, key)) is None
                assert await storage.get(_document_id(kind, key)) is not None
            assert await case.journal.ready()

            # The workflow reads its records at the new addresses.
            current = await case.request("GET", f"/v1/changesets/{change['id']}", actor="bob")
            assert current.status_code == 200, current.text
            receipt_id = current.json()["apply_receipt_id"]
            assert await case.journal.get("ApplyReceipt", receipt_id) is not None
            report = await case.request(
                "GET", f"/v1/changesets/{change['id']}/validation", actor="bob"
            )
            assert report.status_code == 200, report.text

    asyncio.run(run())
