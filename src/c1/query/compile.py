"""Fetch only caller-authorized IDs at one pinned knowledge revision.

The selection planner is responsible for current authorization before calling
this module. GraphQL is only an ID-bounded transport optimization: all
predicates are evaluated on decoded NodeRecords by the query layer.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from c1.model.ids import validate_iri
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry, PropertyDefinition
from c1.storage.mapping import _value_kind, document_to_record, storage_id
from c1.storage.schema import assert_installed_profiles
from c1.storage.terminus import BackendError, StorageError, Terminus

CHUNK_SIZE = 200
FALLBACK_CONCURRENCY = 8
_COMMIT = re.compile(r"(?:branch:|commit:)?([A-Za-z0-9_-]+)\Z")
_BACKEND_ID_BASE = "terminusdb:///data/"
_LITERAL_SELECTION = "{ lexical datatype language }"


class _GraphQLShapeError(Exception):
    """The server's GraphQL representation cannot preserve a NodeRecord."""


class _GraphQLLiteralShapeError(_GraphQLShapeError):
    """One numeric lexical value was coerced; its document must be fetched."""


class _GraphQLRecordFallback(Exception):
    def __init__(self, decoded: dict[str, NodeRecord], requested: dict[str, set[str]]) -> None:
        self.decoded = decoded
        self.requested = requested


def _commit_id(revision: str) -> str:
    match = _COMMIT.fullmatch(revision)
    if match is None:
        raise ValueError("revision must be a knowledge commit identifier")
    return match[1]


def _selection(definition: ClassDefinition) -> str:
    fields = ["_id", "canonical_iri", "types"]
    for prop in definition.properties.values():
        kind = _value_kind(prop)
        if kind == "iri":
            fields.append(prop.name)
        elif kind == "literal":
            fields.append(f"{prop.name} {_LITERAL_SELECTION}")
        else:
            fields.append(f"{prop.name} {{ iri literal {_LITERAL_SELECTION} }}")
    return " ".join(fields)


def _literal(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _GraphQLShapeError
    if not isinstance(value.get("datatype"), str):
        raise _GraphQLShapeError
    language = value.get("language")
    if language is not None and not isinstance(language, str):
        raise _GraphQLShapeError
    if not isinstance(value.get("lexical"), str):
        # Never reconstruct exact lexical spelling from a JSON number. Only
        # this known numeric coercion permits a selective document fallback.
        if type(value.get("lexical")) in {int, float} and value["datatype"] in {
            "http://www.w3.org/2001/XMLSchema#integer",
            "http://www.w3.org/2001/XMLSchema#decimal",
            "http://www.w3.org/2001/XMLSchema#double",
        }:
            raise _GraphQLLiteralShapeError
        raise _GraphQLShapeError
    result = {"@type": "LiteralValue", "lexical": value["lexical"], "datatype": value["datatype"]}
    if language is not None:
        result["language"] = language
    return result


def _value(value: object, prop: PropertyDefinition) -> object:
    kind = _value_kind(prop)
    if kind == "iri":
        if not isinstance(value, str):
            raise _GraphQLShapeError
        return value
    if kind == "literal":
        return _literal(value)
    if not isinstance(value, dict) or set(value) != {"iri", "literal"}:
        raise _GraphQLShapeError
    iri, literal = value["iri"], value["literal"]
    if (iri is None) == (literal is None):
        raise _GraphQLShapeError
    if iri is not None:
        if not isinstance(iri, str):
            raise _GraphQLShapeError
        return {"@type": "Value", "iri": iri}
    return {"@type": "Value", "literal": _literal(literal)}


def _decode(
    item: object, definition: ClassDefinition, registry: ProfileRegistry, base: str
) -> NodeRecord:
    if not isinstance(item, dict):
        raise _GraphQLShapeError
    backend_id = item.get("_id")
    if not isinstance(backend_id, str) or not backend_id.startswith(_BACKEND_ID_BASE):
        raise _GraphQLShapeError
    expected_fields = {"_id", "canonical_iri", "types"} | {
        prop.name for prop in definition.properties.values()
    }
    if set(item) != expected_fields:
        raise _GraphQLShapeError
    doc: dict[str, Any] = {
        "@id": backend_id[len(_BACKEND_ID_BASE) :],
        "@type": definition.storage_name,
        "canonical_iri": item["canonical_iri"],
        "types": item["types"],
    }
    numeric_coercion = False

    def decode_value(value: object, prop: PropertyDefinition) -> object:
        nonlocal numeric_coercion
        try:
            return _value(value, prop)
        except _GraphQLLiteralShapeError:
            numeric_coercion = True
            return None

    for prop in definition.properties.values():
        raw = item[prop.name]
        if raw is None:
            if prop.max_count != 1:
                raise _GraphQLShapeError
            continue
        if prop.max_count == 1:
            doc[prop.name] = decode_value(raw, prop)
        else:
            if not isinstance(raw, list):
                raise _GraphQLShapeError
            # GraphQL reports [] for both absent and stored empty Set fields.
            # Both have the same RDF meaning; use the absent representation.
            if raw:
                doc[prop.name] = [decode_value(value, prop) for value in raw]
    if numeric_coercion:
        raise _GraphQLLiteralShapeError
    try:
        record = document_to_record(doc, registry)
        if storage_id(record, definition, base) != doc["@id"]:
            raise _GraphQLShapeError
    except (StorageError, ValueError, TypeError) as exc:
        raise _GraphQLShapeError from exc
    return record


async def _graphql_chunk(
    storage: Terminus,
    registry: ProfileRegistry,
    definition: ClassDefinition,
    requested: dict[str, set[str]],
    commit_id: str,
) -> dict[str, NodeRecord]:
    backend_ids = [_BACKEND_ID_BASE + backend_id for backend_id in requested]
    query = (
        f"query {{ {definition.storage_name}(ids: {json.dumps(backend_ids)}) "
        f"{{ {_selection(definition)} }} }}"
    )
    path = f"/api/graphql/{storage._database_path}/local/commit/{commit_id}"
    try:
        response = await storage._request("POST", path, json={"query": query})
        payload = response.json()
    except (BackendError, ValueError) as exc:
        raise _GraphQLShapeError from exc
    if (
        not isinstance(payload, dict)
        or payload.get("errors")
        or not isinstance(payload.get("data"), dict)
        or not isinstance(payload["data"].get(definition.storage_name), list)
    ):
        raise _GraphQLShapeError
    result: dict[str, NodeRecord] = {}
    rows = payload["data"][definition.storage_name]
    seen_backend_ids: set[str] = set()
    seen_canonical_ids: set[str] = set()
    # Validate the identities of *every* row before decoding any literal. A
    # malformed row must never turn an unrequested identity into a GET target.
    for item in rows:
        if not isinstance(item, dict):
            raise _GraphQLShapeError
        backend_id = item.get("_id")
        canonical_id = item.get("canonical_iri")
        types = item.get("types")
        if not isinstance(backend_id, str) or not backend_id.startswith(_BACKEND_ID_BASE):
            raise _GraphQLShapeError
        backend_id = backend_id[len(_BACKEND_ID_BASE) :]
        if (
            backend_id not in requested
            or not isinstance(canonical_id, str)
            or canonical_id not in requested[backend_id]
            or backend_id in seen_backend_ids
            or canonical_id in seen_canonical_ids
            or not isinstance(types, list)
            or not all(isinstance(item, str) for item in types)
            or definition.iri not in types
        ):
            raise _GraphQLShapeError
        seen_backend_ids.add(backend_id)
        seen_canonical_ids.add(canonical_id)
    fallback: dict[str, set[str]] = {}
    for item in rows:
        backend_id = item["_id"][len(_BACKEND_ID_BASE) :]
        try:
            record = _decode(item, definition, registry, storage.config.instance_base)
        except _GraphQLLiteralShapeError:
            fallback[backend_id] = requested[backend_id]
            continue
        backend_id = storage_id(record, definition, storage.config.instance_base)
        if (
            backend_id not in requested
            or record.id not in requested[backend_id]
            or record.id in result
        ):
            raise _GraphQLShapeError
        result[record.id] = record
    if fallback:
        raise _GraphQLRecordFallback(result, fallback)
    return result


async def _get_chunk(
    storage: Terminus,
    registry: ProfileRegistry,
    definition: ClassDefinition,
    requested: dict[str, set[str]],
    commit_id: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, NodeRecord]:
    async def one(backend_id: str, canonical_ids: set[str]) -> NodeRecord | None:
        async with semaphore:
            document = await storage.get(backend_id, commit=commit_id)
        if document is None:
            return None
        record = document_to_record(document, registry)
        if (
            record.id not in canonical_ids
            or registry.primary_class(record.types).iri != definition.iri
            or storage_id(record, definition, storage.config.instance_base) != backend_id
        ):
            raise StorageError("C1-ST-005", "stored ID does not match canonical identity")
        return record

    tasks = [
        asyncio.create_task(one(backend_id, canonical_ids))
        for backend_id, canonical_ids in requested.items()
    ]
    try:
        found = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return {record.id: record for record in found if record is not None}


async def _fetch_records_content(
    storage: Terminus,
    registry: ProfileRegistry,
    requested_ids: list[str],
    commit_id: str,
    *,
    backend_gate: asyncio.Semaphore,
    storage_types: Mapping[str, frozenset[str]] | None,
) -> dict[str, NodeRecord]:
    """Collect pinned content; only authority-gated wrappers may expose it."""
    result: dict[str, NodeRecord] = {}
    semaphore = backend_gate
    chunks: list[tuple[ClassDefinition, dict[str, set[str]]]] = []
    for definition in registry.classes.values():
        class_ids: dict[str, set[str]] = {}
        for canonical_id in requested_ids:
            hint = storage_types.get(canonical_id) if storage_types is not None else None
            if hint and hint <= registry.classes.keys() and definition.iri not in hint:
                continue
            candidate = NodeRecord(id=canonical_id, types=[definition.iri], properties={})
            try:
                backend_id = storage_id(candidate, definition, storage.config.instance_base)
            except StorageError as exc:
                if exc.code == "C1-ST-004":
                    continue
                raise
            class_ids.setdefault(backend_id, set()).add(canonical_id)
        pairs = list(class_ids.items())
        for start in range(0, len(pairs), CHUNK_SIZE):
            chunks.append((definition, dict(pairs[start : start + CHUNK_SIZE])))

    async def one(definition: ClassDefinition, chunk: dict[str, set[str]]) -> dict[str, NodeRecord]:
        try:
            async with semaphore:
                return await _graphql_chunk(storage, registry, definition, chunk, commit_id)
        except _GraphQLRecordFallback as fallback:
            found = await _get_chunk(
                storage, registry, definition, fallback.requested, commit_id, semaphore
            )
            if set(found).intersection(fallback.decoded):
                raise StorageError(
                    "C1-ST-005", "duplicate canonical identity in fallback"
                ) from None
            return {**fallback.decoded, **found}
        except _GraphQLShapeError:
            return await _get_chunk(storage, registry, definition, chunk, commit_id, semaphore)

    tasks = [asyncio.create_task(one(definition, chunk)) for definition, chunk in chunks]
    try:
        fetched_chunks = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    for found in fetched_chunks:
        for canonical_id, record in found.items():
            if canonical_id in result:
                raise StorageError("C1-ST-005", "canonical identity resolves to multiple documents")
            result[canonical_id] = record
    return result


async def fetch_records(
    storage: Terminus,
    registry: ProfileRegistry,
    ids: Iterable[str],
    *,
    revision: str | None = None,
    backend_gate: asyncio.Semaphore | None = None,
    storage_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, NodeRecord]:
    """Return preauthorized IDs only after this fetch's fresh profile checks.

    Complete historical type hints are caller responsibilities. Unknown hints
    preserve all-class probes; numeric lexical coercions use exact document GET.
    """
    requested_ids = list(dict.fromkeys(ids))
    for canonical_id in requested_ids:
        validate_iri(canonical_id)
    if not requested_ids:
        return {}
    if revision is None:
        revision = await storage.head()
    commit_id = _commit_id(revision)
    gate = backend_gate or asyncio.Semaphore(FALLBACK_CONCURRENCY)
    authority_task = asyncio.create_task(
        assert_installed_profiles(storage, registry, backend_gate=gate)
    )
    content_task = asyncio.create_task(
        _fetch_records_content(
            storage,
            registry,
            requested_ids,
            commit_id,
            backend_gate=gate,
            storage_types=storage_types,
        )
    )
    try:
        await asyncio.gather(authority_task, content_task)
    except BaseException:
        for task in (authority_task, content_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(authority_task, content_task, return_exceptions=True)
        raise
    return content_task.result()


class _HistoricalPreparation:
    """One request's independently started authority for its first cohort."""

    def __init__(
        self,
        storage: Terminus,
        registry: ProfileRegistry,
        backend_gate: asyncio.Semaphore,
        origin: object,
        workflow_head: str,
        deadline: float,
    ) -> None:
        self._storage = storage
        self._registry = registry
        self._backend_gate = backend_gate
        self._origin = origin
        self._workflow_head = workflow_head
        self._deadline = deadline
        self._used = False
        self._closed = False
        self._collection: asyncio.Task[dict[str, dict[str, NodeRecord]]] | None = None
        self._authority = asyncio.create_task(self._check())

    @property
    def registry(self) -> ProfileRegistry:
        return self._registry

    async def _check(self) -> None:
        async with asyncio.timeout_at(self._deadline):
            await assert_installed_profiles(
                self._storage, self._registry, backend_gate=self._backend_gate
            )

    def _validate(
        self,
        storage: Terminus,
        registry: ProfileRegistry,
        backend_gate: asyncio.Semaphore,
        origin: object,
        workflow_head: str,
        deadline: float,
    ) -> None:
        if (
            self._closed
            or self._used
            or storage is not self._storage
            or registry is not self._registry
            or backend_gate is not self._backend_gate
            or origin is not self._origin
            or workflow_head != self._workflow_head
            or deadline != self._deadline
        ):
            raise ValueError("historical preparation does not match this cohort")

    async def close(self) -> None:
        """Cancel and await unused work, or observe already completed work."""
        self._closed = True
        tasks = (
            [self._authority] if self._collection is None else [self._authority, self._collection]
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _snapshot_inputs(ids: Iterable[str], revisions: list[str]) -> tuple[list[str], list[str]]:
    if len(revisions) > 8 or len(set(revisions)) != len(revisions):
        raise ValueError("snapshot cohort must contain at most eight distinct revisions")
    commits = [_commit_id(revision) for revision in revisions]
    requested_ids = list(dict.fromkeys(ids))
    for canonical_id in requested_ids:
        validate_iri(canonical_id)
    return requested_ids, commits


async def _collect_record_snapshots(
    storage: Terminus,
    registry: ProfileRegistry,
    requested_ids: list[str],
    revisions: list[str],
    commits: list[str],
    authority_task: asyncio.Task[None],
    *,
    backend_gate: asyncio.Semaphore,
    storage_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, dict[str, NodeRecord]]:
    snapshots = [
        asyncio.create_task(
            _fetch_records_content(
                storage,
                registry,
                requested_ids,
                commit,
                backend_gate=backend_gate,
                storage_types=storage_types,
            )
        )
        for commit in commits
    ]
    try:
        await asyncio.gather(authority_task, *snapshots)
    except BaseException:
        for task in (authority_task, *snapshots):
            if not task.done():
                task.cancel()
        await asyncio.gather(authority_task, *snapshots, return_exceptions=True)
        raise
    return {revision: task.result() for revision, task in zip(revisions, snapshots, strict=True)}


async def fetch_record_snapshots(
    storage: Terminus,
    registry: ProfileRegistry,
    ids: Iterable[str],
    revisions: list[str],
    *,
    backend_gate: asyncio.Semaphore,
    storage_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, dict[str, NodeRecord]]:
    """Gate at most eight historical snapshots on one NEW current authority read."""
    requested_ids, commits = _snapshot_inputs(ids, revisions)
    if not requested_ids or not revisions:
        return {revision: {} for revision in revisions}
    authority = asyncio.create_task(
        assert_installed_profiles(storage, registry, backend_gate=backend_gate)
    )
    return await _collect_record_snapshots(
        storage,
        registry,
        requested_ids,
        revisions,
        commits,
        authority,
        backend_gate=backend_gate,
        storage_types=storage_types,
    )


async def _fetch_prepared_snapshots(
    storage: Terminus,
    registry: ProfileRegistry,
    ids: Iterable[str],
    revisions: list[str],
    preparation: _HistoricalPreparation,
    *,
    origin: object,
    workflow_head: str,
    deadline: float,
    backend_gate: asyncio.Semaphore,
    storage_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, dict[str, NodeRecord]]:
    requested_ids, commits = _snapshot_inputs(ids, revisions)
    if len(set(commits)) != len(commits):
        raise ValueError("prepared cohort must contain distinct pinned commits")
    preparation._validate(storage, registry, backend_gate, origin, workflow_head, deadline)
    if not requested_ids or not revisions:
        return {revision: {} for revision in revisions}
    preparation._used = True
    collection = asyncio.create_task(
        _collect_record_snapshots(
            storage,
            registry,
            requested_ids,
            revisions,
            commits,
            preparation._authority,
            backend_gate=backend_gate,
            storage_types=storage_types,
        )
    )
    preparation._collection = collection
    try:
        return await collection
    except BaseException:
        if not collection.done():
            collection.cancel()
        # Cancellation may happen before the collector's first turn, before
        # its own cleanup can take ownership of the independent authority.
        if not preparation._authority.done():
            preparation._authority.cancel()
        await asyncio.gather(collection, preparation._authority, return_exceptions=True)
        raise
