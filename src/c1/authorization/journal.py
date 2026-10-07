"""Durable operational journal in the configured TerminusDB workflow database.

Knowledge records and workflow envelopes are separate databases. Each
``save_many`` call writes all requested envelopes in one head-checked backend
commit. This does not imply a transaction with knowledge or OpenFGA.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any, Self

import httpx

from c1 import roundtrips
from c1.authorization.view import SecurityView
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
        # M13: operational restore records (knowledge restore, disaster-recovery guard).
        "Restore",
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
# M14b D4 (ADR-0026): kinds that are only ever read by ID live in their own
# class, so the listing every step reloads holds only listed kinds.
_RECORD_KINDS = frozenset(
    {"ValidationReport", "ReviewDecision", "ApplyReceipt", "Idempotency", "MigrationProposal"}
)
_RECORD_CLASS = {**_ENTRY_CLASS, "@id": "WorkflowRecord"}
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


def _class_of(kind: str) -> str:
    return "WorkflowRecord" if kind in _RECORD_KINDS else "WorkflowEntry"


def _document_id(kind: str, key: str) -> str:
    _validate_address(kind, key)
    digest = hashlib.sha256(f"{kind}\0{key}".encode()).hexdigest()
    return f"{_class_of(kind)}/{digest}"


def _legacy_id(kind: str, key: str) -> str:
    """The pre-M14b address of every kind (one class)."""
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
        "@type": _class_of(kind),
        "@id": document_id,
        "kind": kind,
        "key": key,
        "payload_json": payload_json,
    }


def _decode(document: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if document.get("@type") not in ("WorkflowEntry", "WorkflowRecord"):
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
    if document.get("@id") != expected_id or document.get("@type") != _class_of(kind):
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
        # The last full listing and the exact data version it was served at.
        # A data version identifies content, so the listing is reused only when
        # a fresh head read returns that same version; any write changes it.
        self._snapshot: tuple[str, list[tuple[str, str, dict[str, Any]]]] | None = None
        self._view: SecurityView | None = None

    async def __aenter__(self) -> Self:
        await self._storage.__aenter__()
        return self

    async def __aexit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        await self._storage.__aexit__(_type, _value, _traceback)

    async def initialize(self, *, deployment: bool = False) -> None:
        """Create a fresh workflow database and typed schema.

        Tests create isolated databases; `deployment=True` is the one-time
        M13 bootstrap of a deployment's workflow database.
        """
        if deployment:
            await self._storage.create_for_deployment()
        else:
            await self._storage.create()
        base = await self._storage.head()
        await self._storage._insert(
            [_ENTRY_CLASS, _RECORD_CLASS],
            expected_head=base,
            message="Install C1 workflow journal schema",
            graph_type="schema",
        )

    async def migrate_records(self) -> int:
        """Move ID-only kinds into their own class (M14b D4); idempotent.

        Runs at startup before C1 serves. Two commits: copy to the new class,
        then remove the old copies. A crash in between leaves both copies, and
        the next run finishes; readers use the new address.
        """
        schema = await self._storage.schema_documents()
        legacy_schema = len(schema) == 2 and _DEFAULT_CONTEXT in schema and _ENTRY_CLASS in schema
        if not legacy_schema and not await self.ready():
            raise StorageError("C1-JR-001", "workflow database schema is not a C1 journal schema")
        if _RECORD_CLASS not in schema:
            await self._storage._insert(
                [_RECORD_CLASS],
                expected_head=await self.head(),
                message="M14b: add the workflow record class",
                graph_type="schema",
            )
        _version, documents = await self._storage.documents_at_version(type="WorkflowEntry")
        legacy: list[tuple[str, str, dict[str, Any]]] = []
        for document in documents:
            kind, key = document.get("kind"), document.get("key")
            if kind in _RECORD_KINDS and isinstance(key, str):
                if document.get("@id") != _legacy_id(kind, key):
                    raise StorageError(
                        "C1-JR-001", "workflow envelope ID does not match its address"
                    )
                payload = json.loads(str(document.get("payload_json")))
                legacy.append((kind, key, payload))
        if not legacy:
            return 0
        for start in range(0, len(legacy), 500):
            await self._storage._put(
                [_encode(*entry) for entry in legacy[start : start + 500]],
                expected_head=await self.head(),
                message="M14b: copy workflow records to their class",
                create=True,
            )
        for start in range(0, len(legacy), 500):
            await self._storage._delete(
                [_legacy_id(kind, key) for kind, key, _ in legacy[start : start + 500]],
                expected_head=await self.head(),
                message="M14b: remove copied workflow records",
            )
        self._snapshot = None
        self._view = None
        return len(legacy)

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
        return (
            len(schema) == 3
            and _DEFAULT_CONTEXT in schema
            and _ENTRY_CLASS in schema
            and _RECORD_CLASS in schema
        )

    async def get(self, kind: str, id: str) -> dict[str, Any] | None:
        document = await self._storage.get(_document_id(kind, id))
        if document is None:
            return None
        actual_kind, actual_key, payload = _decode(document)
        if (actual_kind, actual_key) != (kind, id):
            raise StorageError("C1-JR-001", "workflow address collision")
        return payload

    @roundtrips.phased("journal.view")
    async def _versioned_entries(
        self,
    ) -> tuple[str, builtins.list[tuple[str, str, dict[str, Any]]]]:
        snapshot = self._snapshot
        if snapshot is not None and await self.head() == snapshot[0]:
            return snapshot
        version, documents = await self._storage.documents_at_version(type="WorkflowEntry")
        decoded = [_decode(document) for document in documents]
        self._snapshot = (version, decoded)
        self._view = None
        return version, decoded

    async def _entries(self) -> builtins.list[tuple[str, str, dict[str, Any]]]:
        return (await self._versioned_entries())[1]

    async def view(self) -> SecurityView:
        """The security projection at the data version of one listing (M09a D1).

        Built once per data version and shared read-only; callers compare
        `view.version` with the head they read before deciding.
        """
        version, entries = await self._versioned_entries()
        cached = self._view
        if cached is not None and cached.version == version:
            return cached
        view = SecurityView.build(version, entries)
        self._view = view
        return view

    async def list(self, kind: str) -> list[dict[str, Any]]:
        if kind not in _KINDS:
            raise ValueError("unsupported journal kind")
        return (await self.list_many({kind}))[kind]

    async def list_many(self, kinds: set[str]) -> dict[str, builtins.list[dict[str, Any]]]:
        """Read one consistent workflow document enumeration for several kinds.

        M14b D4: ID-only kinds live in the record class, which the per-step
        listing does not hold; asking for one also lists that class, at the
        same data version as the entries (retried if a write lands between).
        """
        if not kinds or not kinds.issubset(_KINDS):
            raise ValueError("unsupported journal kind")
        result: dict[str, builtins.list[dict[str, Any]]] = {kind: [] for kind in kinds}
        if kinds & _RECORD_KINDS:
            entries = await self._entries_with_records()
        else:
            entries = await self._entries()
        for kind, _key, payload in entries:
            if kind in result:
                result[kind].append(copy.deepcopy(payload))
        return result

    async def _entries_with_records(self) -> builtins.list[tuple[str, str, dict[str, Any]]]:
        for _attempt in range(5):
            version, entries = await self._versioned_entries()
            record_version, documents = await self._storage.documents_at_version(
                type="WorkflowRecord"
            )
            if record_version == version:
                return [*entries, *(_decode(document) for document in documents)]
        raise StorageError("C1-JR-002", "workflow journal changed during enumeration")

    @roundtrips.phased("journal.save")
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
