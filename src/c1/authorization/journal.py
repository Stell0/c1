"""Durable operational journal in the configured TerminusDB workflow database.

Knowledge records and workflow envelopes are separate databases. Each
``save_many`` call writes all requested envelopes in one head-checked backend
commit. This does not imply a transaction with knowledge or OpenFGA.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any, Self

import httpx

from c1.storage.terminus import StorageConfig, StorageError, Terminus

_KINDS = frozenset(
    {
        "Scope",
        "Binding",
        "Operation",
        "ChangeSet",
        "ValidationReport",
        "ReviewDecision",
        "ApplyReceipt",
        "Idempotency",
        "MigrationProposal",
    }
)
_ENTRY_CLASS = {
    "@type": "Class",
    "@id": "WorkflowEntry",
    "@key": {"@type": "Random"},
    "kind": "xsd:string",
    "key": "xsd:string",
    "payload_json": "xsd:string",
}
_DEFAULT_CONTEXT = {
    "@type": "@context",
    "@base": "terminusdb:///data/",
    "@schema": "terminusdb:///schema#",
}
_BAD_KEY = re.compile(r"[\x00-\x1f\x7f]")


def _validate_address(kind: str, key: str) -> None:
    if kind not in _KINDS:
        raise ValueError("unsupported journal kind")
    if not isinstance(key, str) or not key or len(key) > 2048 or _BAD_KEY.search(key):
        raise ValueError("journal key must be nonempty, bounded text without controls")


def _document_id(kind: str, key: str) -> str:
    _validate_address(kind, key)
    digest = hashlib.sha256(f"{kind}\0{key}".encode()).hexdigest()
    return f"WorkflowEntry/{digest}"


def _encode(kind: str, key: str, payload: dict[str, Any]) -> dict[str, str]:
    document_id = _document_id(kind, key)
    if not isinstance(payload, dict) or any(not isinstance(item, str) for item in payload):
        raise ValueError("journal payload must be a JSON object with string keys")
    try:
        payload_json = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("journal payload must be JSON-compatible") from exc
    return {
        "@type": "WorkflowEntry",
        "@id": document_id,
        "kind": kind,
        "key": key,
        "payload_json": payload_json,
    }


def _decode(document: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if document.get("@type") != "WorkflowEntry":
        raise StorageError("C1-JR-001", "workflow document has an unknown type")
    kind = document.get("kind")
    key = document.get("key")
    text = document.get("payload_json")
    if not isinstance(kind, str) or not isinstance(key, str) or not isinstance(text, str):
        raise StorageError("C1-JR-001", "workflow envelope lacks required fields")
    try:
        expected_id = _document_id(kind, key)
    except ValueError as exc:
        raise StorageError("C1-JR-001", "workflow envelope has an invalid address") from exc
    if document.get("@id") != expected_id:
        raise StorageError("C1-JR-001", "workflow envelope ID does not match its address")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError("C1-JR-001", "workflow envelope has invalid JSON") from exc
    if not isinstance(payload, dict):
        raise StorageError("C1-JR-001", "workflow payload is not an object")
    if any(not isinstance(item, str) for item in payload):
        raise StorageError("C1-JR-001", "workflow payload keys are invalid")
    return kind, key, payload


class Journal:
    """Internal workflow journal; database routing is fixed by StorageConfig."""

    def __init__(self, config: StorageConfig) -> None:
        self._storage = Terminus(config)

    async def __aenter__(self) -> Self:
        await self._storage.__aenter__()
        return self

    async def __aexit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        await self._storage.__aexit__(_type, _value, _traceback)

    async def initialize(self) -> None:
        """Create a fresh, isolated test workflow database and typed schema."""
        await self._storage.create()
        base = await self._storage.head()
        await self._storage._insert(
            [_ENTRY_CLASS],
            expected_head=base,
            message="Install C1 workflow journal schema",
            graph_type="schema",
        )

    async def drop_test_database(self) -> None:
        await self._storage.drop()

    async def head(self) -> str:
        return await self._storage.head()

    async def ready(self) -> bool:
        try:
            await self.head()
            schema = await self._storage.schema_documents()
        except (StorageError, httpx.HTTPError, OSError):
            return False
        return len(schema) == 2 and _DEFAULT_CONTEXT in schema and _ENTRY_CLASS in schema

    async def get(self, kind: str, id: str) -> dict[str, Any] | None:
        document = await self._storage.get(_document_id(kind, id))
        if document is None:
            return None
        actual_kind, actual_key, payload = _decode(document)
        if (actual_kind, actual_key) != (kind, id):
            raise StorageError("C1-JR-001", "workflow address collision")
        return payload

    async def list(self, kind: str) -> list[dict[str, Any]]:
        if kind not in _KINDS:
            raise ValueError("unsupported journal kind")
        documents = await self._storage.documents()
        decoded = [_decode(document) for document in documents]
        return [payload for actual_kind, _key, payload in decoded if actual_kind == kind]

    async def save_many(
        self,
        entries: Sequence[tuple[str, str, dict[str, Any]]],
        expected_head: str | None = None,
    ) -> str:
        if not entries:
            raise ValueError("journal batch must not be empty")
        documents = [_encode(kind, key, payload) for kind, key, payload in entries]
        ids = [document["@id"] for document in documents]
        if len(set(ids)) != len(ids):
            raise ValueError("journal batch contains the same kind/key twice")
        base = expected_head if expected_head is not None else await self.head()
        return await self._storage._put(
            documents,
            expected_head=base,
            message="C1 security journal batch",
            create=True,
        )
