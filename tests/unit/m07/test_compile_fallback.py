"""Selective precise literal reads preserve identity checks and shared bounds."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import httpx
import pytest

import c1.query.compile as compiler
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, RDF, AssertionRecord
from c1.storage.mapping import record_to_document
from c1.storage.terminus import StorageConfig, StorageError, Terminus

BASE = "urn:c1:instance:dev:"
XSD = "http://www.w3.org/2001/XMLSchema#"


def assertion(name: str, obj: str | LiteralValue) -> NodeRecord:
    return AssertionRecord(
        id="urn:test:" + name,
        subject="urn:test:subject",
        predicate="urn:test:predicate",
        object=obj,
        origin="manual",
    ).to_node()


def graphql_value(raw: Any) -> Any:
    if isinstance(raw, list):
        return [graphql_value(item) for item in raw]
    if not isinstance(raw, dict):
        return raw
    if raw["@type"] == "LiteralValue":
        return {key: raw.get(key) for key in ("lexical", "datatype", "language")}
    return {"iri": raw.get("iri"), "literal": graphql_value(raw.get("literal"))}


def rows_for(
    records: list[NodeRecord], registry: ProfileRegistry
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    definition = registry.classes[C1 + "Assertion"]
    documents = {record.id: record_to_document(record, registry, BASE) for record in records}
    rows = [
        {
            "_id": "terminusdb:///data/" + documents[record.id]["@id"],
            "canonical_iri": record.id,
            "types": record.types,
            **{
                prop.name: graphql_value(
                    documents[record.id].get(prop.name, None if prop.max_count == 1 else [])
                )
                for prop in definition.properties.values()
            },
        }
        for record in records
    ]
    return rows, {doc["@id"]: doc for doc in documents.values()}


async def installed(
    _storage: Terminus,
    _registry: ProfileRegistry,
    *,
    backend_gate: asyncio.Semaphore | None = None,
) -> None:
    pass


def storage(handler: Any) -> Terminus:
    value = Terminus(
        StorageConfig(
            url="http://127.0.0.1:16363",
            password="synthetic",  # pragma: allowlist secret - local fake credential
            organization="admin",
            database="c1_m07_synthetic",
            instance_base=BASE,
        )
    )
    value._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:16363", transport=httpx.MockTransport(handler)
    )
    return value


def test_only_coerced_record_get_retains_exact_decimal_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    good = assertion("good", "urn:test:object")
    numeric = assertion("numeric", LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
    rows, documents = rows_for([good, numeric], registry)
    rows[1]["object"]["literal"]["lexical"] = 42.5
    get_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/local/commit/old")
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"Assertion": rows}})
        identifier = request.url.params["id"]
        get_ids.append(identifier)
        return httpx.Response(200, json=[documents[identifier]])

    async def run() -> None:
        async with storage(handler) as client:
            actual = await compiler.fetch_records(
                client,
                registry,
                [good.id, numeric.id],
                revision="branch:old",
                storage_types={node.id: frozenset(node.types) for node in [good, numeric]},
            )
            assert actual == {good.id: good, numeric.id: numeric}
            assert actual[numeric.id].properties[RDF + "object"][0] == LiteralValue(
                lexical="42.5000", datatype=XSD + "decimal"
            )

    asyncio.run(run())
    assert get_ids == [
        next(key for key, doc in documents.items() if doc["canonical_iri"] == numeric.id)
    ]


@pytest.mark.parametrize(
    "malformation",
    [
        "unexpected_id",
        "duplicate_id",
        "wrong_canonical",
        "wrong_types",
        "missing_field",
        "bad_other_field",
    ],
)
def test_unsupported_or_unrequested_rows_force_whole_chunk_fallback(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    good = assertion("good", "urn:test:object")
    numeric = assertion("numeric", LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
    rows, documents = rows_for([good, numeric], registry)
    rows[1]["object"]["literal"]["lexical"] = 42.5
    if malformation == "unexpected_id":
        rows[0]["_id"] = "terminusdb:///data/Assertion/hidden"
    elif malformation == "duplicate_id":
        rows.append(copy.deepcopy(rows[1]))
    elif malformation == "wrong_canonical":
        rows[0]["canonical_iri"] = "urn:test:hidden"
    elif malformation == "wrong_types":
        rows[1]["types"] = [C1 + "Source"]
    elif malformation == "missing_field":
        del rows[0]["reviewState"]
    else:
        rows[1]["reviewState"] = {"lexical": False, "datatype": XSD + "string", "language": None}
    get_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"Assertion": rows}})
        identifier = request.url.params["id"]
        get_ids.append(identifier)
        assert identifier in documents  # Never fetch the unexpected backend identity.
        return httpx.Response(200, json=[documents[identifier]])

    async def run() -> None:
        async with storage(handler) as client:
            actual = await compiler.fetch_records(
                client,
                registry,
                [good.id, numeric.id],
                revision="old",
                storage_types={node.id: frozenset(node.types) for node in [good, numeric]},
            )
            assert actual == {good.id: good, numeric.id: numeric}
            assert "urn:test:hidden" not in actual

    asyncio.run(run())
    assert set(get_ids) == set(documents)


def test_partial_fallback_rejects_document_with_wrong_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    good = assertion("good", "urn:test:object")
    numeric = assertion("numeric", LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
    rows, documents = rows_for([good, numeric], registry)
    rows[1]["object"]["literal"]["lexical"] = 42.5

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"Assertion": rows}})
        doc = {**documents[request.url.params["id"]], "canonical_iri": "urn:test:hidden"}
        return httpx.Response(200, json=[doc])

    async def run() -> None:
        async with storage(handler) as client:
            with pytest.raises(StorageError, match="stored ID does not match"):
                await compiler.fetch_records(
                    client,
                    registry,
                    [good.id, numeric.id],
                    revision="old",
                    storage_types={node.id: frozenset(node.types) for node in [good, numeric]},
                )

    asyncio.run(run())


def test_partial_fallback_timeout_cancels_and_awaits_every_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    records = [
        assertion(str(index), LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
        for index in range(2)
    ]
    rows, _ = rows_for(records, registry)
    for row in rows:
        row["object"]["literal"]["lexical"] = 42.5
    active = 0
    peak = 0
    completed = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, completed
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"Assertion": rows}})
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            active -= 1
            completed += 1
        raise AssertionError("unreachable")

    async def run() -> None:
        async with storage(handler) as client:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.03):
                    await compiler.fetch_records(
                        client,
                        registry,
                        [record.id for record in records],
                        revision="old",
                        backend_gate=asyncio.Semaphore(2),
                        storage_types={node.id: frozenset(node.types) for node in records},
                    )
        assert active == 0 and completed == 2 and peak == 2

    asyncio.run(run())


def test_partial_fallback_uses_shared_gate_across_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "assert_installed_profiles", installed)
    registry = ProfileRegistry()
    records = [
        assertion(str(index), LiteralValue(lexical="42.5000", datatype=XSD + "decimal"))
        for index in range(2)
    ]
    rows, documents = rows_for(records, registry)
    for row in rows:
        row["object"]["literal"]["lexical"] = 42.5
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.002)
            if request.method == "POST":
                return httpx.Response(200, json={"data": {"Assertion": rows}})
            return httpx.Response(200, json=[documents[request.url.params["id"]]])
        finally:
            active -= 1

    async def run() -> None:
        async with storage(handler) as client:
            gate = asyncio.Semaphore(2)
            result = await asyncio.gather(
                *[
                    compiler.fetch_records(
                        client,
                        registry,
                        [record.id for record in records],
                        revision="old",
                        backend_gate=gate,
                        storage_types={node.id: frozenset(node.types) for node in records},
                    )
                    for _ in range(3)
                ]
            )
            assert all(value == {node.id: node for node in records} for value in result)
        assert active == 0 and peak == 2

    asyncio.run(run())
