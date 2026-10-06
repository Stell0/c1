"""M14b D4 (ADR-0026): ID-only journal kinds live in their own class."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from c1.authorization.journal import (
    _ENTRY_CLASS,
    _RECORD_CLASS,
    Journal,
    _decode,
    _document_id,
    _encode,
    _legacy_id,
)
from c1.storage.terminus import StorageConfig, StorageError


class FakeStorage:
    def __init__(self, schema: list[dict[str, Any]], documents: list[dict[str, Any]]) -> None:
        self.schema = schema
        self.documents = {d["@id"]: d for d in documents}
        self.version = 0
        self.fail_after_put = False

    async def head(self) -> str:
        return f"branch:v{self.version}"

    async def schema_documents(self) -> list[dict[str, Any]]:
        return list(self.schema)

    async def _insert(self, documents: list[dict[str, Any]], **_: Any) -> str:
        self.schema.extend(documents)
        self.version += 1
        return await self.head()

    async def documents_at_version(self, *, type: str | None = None) -> tuple[str, list[Any]]:
        listed = [d for d in self.documents.values() if type is None or d["@type"] == type]
        return await self.head(), listed

    async def _put(self, documents: list[dict[str, Any]], **_: Any) -> str:
        for document in documents:
            self.documents[document["@id"]] = document
        self.version += 1
        if self.fail_after_put:
            self.fail_after_put = False
            raise RuntimeError("crash between the two migration commits")
        return await self.head()

    async def _delete(self, ids: list[str], **_: Any) -> str:
        for identifier in ids:
            del self.documents[identifier]
        self.version += 1
        return await self.head()

    async def get(self, identifier: str, commit: str | None = None) -> dict[str, Any] | None:
        return self.documents.get(identifier)


def _legacy(kind: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "@type": "WorkflowEntry",
        "@id": _legacy_id(kind, key),
        "kind": kind,
        "key": key,
        "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
    }


def _journal(storage: FakeStorage) -> Journal:
    journal = Journal(StorageConfig("http://127.0.0.1:1", "x", "admin", "c1_w", "urn:c1:i:"))
    journal._storage = storage  # type: ignore[assignment]
    return journal


def test_record_kinds_have_their_own_class_and_entries_keep_theirs() -> None:
    record = _encode("Idempotency", "k1", {"a": 1})
    entry = _encode("Binding", "r1", {"b": 2})
    assert record["@type"] == "WorkflowRecord" and record["@id"].startswith("WorkflowRecord/")
    assert entry["@type"] == "WorkflowEntry" and entry["@id"] == _legacy_id("Binding", "r1")
    assert _decode(record) == ("Idempotency", "k1", {"a": 1})
    misplaced = {**record, "@type": "WorkflowEntry"}
    with pytest.raises(StorageError):
        _decode(misplaced)


def test_migration_moves_records_is_idempotent_and_resumes_after_a_crash() -> None:
    async def run() -> None:
        storage = FakeStorage(
            [_ENTRY_CLASS],
            [
                _legacy("Idempotency", "k1", {"a": 1}),
                _legacy("ValidationReport", "v1", {"ok": True}),
                _legacy("Binding", "r1", {"b": 2}),
                _legacy("Operation", "o1", {"c": 3}),
            ],
        )
        journal = _journal(storage)
        storage.fail_after_put = True
        with pytest.raises(RuntimeError):
            await journal.migrate_records()
        # Both copies exist after the crash; readers use the new address.
        assert await journal.get("Idempotency", "k1") == {"a": 1}
        assert await journal.migrate_records() == 2
        assert await journal.migrate_records() == 0
        assert _RECORD_CLASS in storage.schema
        assert set(storage.documents) == {
            _document_id("Idempotency", "k1"),
            _document_id("ValidationReport", "v1"),
            _document_id("Binding", "r1"),
            _document_id("Operation", "o1"),
        }
        assert await journal.get("ValidationReport", "v1") == {"ok": True}
        # The per-step listing holds only listed kinds.
        assert {kind for kind, _key, _payload in await journal._entries()} == {
            "Binding",
            "Operation",
        }

    asyncio.run(run())
