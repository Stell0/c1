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
    if not isinstance(value, dict) or not isinstance(value.get("lexical"), str):
        # The pinned GraphQL server turns some decimal/integer lexical strings
        # into JSON numbers. Never reconstruct a lexical value from a number.
        raise _GraphQLShapeError
    if not isinstance(value.get("datatype"), str):
        raise _GraphQLShapeError
    language = value.get("language")
    if language is not None and not isinstance(language, str):
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
    for prop in definition.properties.values():
        raw = item[prop.name]
        if raw is None:
            if prop.max_count != 1:
                raise _GraphQLShapeError
            continue
        if prop.max_count == 1:
            doc[prop.name] = _value(raw, prop)
        else:
            if not isinstance(raw, list):
                raise _GraphQLShapeError
            # GraphQL reports [] for both absent and stored empty Set fields.
            # Both have the same RDF meaning; use the absent representation.
            if raw:
                doc[prop.name] = [_value(value, prop) for value in raw]
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
    for item in payload["data"][definition.storage_name]:
        record = _decode(item, definition, registry, storage.config.instance_base)
        backend_id = storage_id(record, definition, storage.config.instance_base)
        if (
            backend_id not in requested
            or record.id not in requested[backend_id]
            or record.id in result
        ):
            raise _GraphQLShapeError
        result[record.id] = record
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


async def fetch_records(
    storage: Terminus,
    registry: ProfileRegistry,
    ids: Iterable[str],
    *,
    revision: str | None = None,
    backend_gate: asyncio.Semaphore | None = None,
    storage_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, NodeRecord]:
    """Return existing records among preauthorized IDs at one knowledge commit.

    Authorization, candidate bounds, and complete historical type hints are
    caller responsibilities. Unknown hints preserve all-class probes. No class
    scans or predicates are sent to TerminusDB. A GraphQL shape that loses
    literal lexical identity falls back to document GET for its entire chunk.
    """
    requested_ids = list(dict.fromkeys(ids))
    for canonical_id in requested_ids:
        validate_iri(canonical_id)
    if not requested_ids:
        return {}
    if revision is None:
        revision = await storage.head()
    commit_id = _commit_id(revision)
    if backend_gate is None:
        await assert_installed_profiles(storage, registry)
    else:
        async with backend_gate:
            await assert_installed_profiles(storage, registry)
    result: dict[str, NodeRecord] = {}
    semaphore = backend_gate or asyncio.Semaphore(FALLBACK_CONCURRENCY)
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
        except _GraphQLShapeError:
            return await _get_chunk(storage, registry, definition, chunk, commit_id, semaphore)

    # The same semaphore bounds all network reads, including fallback GETs.
    # Gather preserves chunk order so collision checking remains deterministic.
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
