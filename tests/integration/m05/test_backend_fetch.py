"""Pinned TerminusDB GraphQL ID chunks and exact historical document fallback."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from rdflib.compare import isomorphic

from c1.interchange import graph_from_records, import_jsonld
from c1.interchange.jsonld import validate_records
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.query.compile import fetch_records
from tests.integration.m02.conftest import live_knowledge

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real TerminusDB required"),
]
ROOT = Path(__file__).resolve().parents[3]
C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def test_backend_fetch_by_ids_and_historical_commit() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        fixture = json.loads((ROOT / "fixtures/core-knowledge/fixture.jsonld").read_text())
        batch = import_jsonld(fixture, registry)
        entity = next(record for record in batch.records if C1 + "Entity" in record.types)
        numeric = next(
            record
            for record in batch.records
            if C1 + "Assertion" in record.types
            and any(
                isinstance(value, LiteralValue) and value.datatype == XSD + "decimal"
                for value in record.properties.get(RDF + "object", [])
            )
        )
        missing_ids = [
            f"urn:c1:instance:dev:entity/{index:08x}-0000-4000-8000-000000000000"
            for index in range(1000, 1200)
        ]
        requested = [*missing_ids, entity.id, numeric.id]
        async with live_knowledge(registry) as db:
            old = await db.write_records(batch, registry, expected_head=await db.head())
            first_page = await db.documents_page(skip=0, count=30, commit=old)
            second_page = await db.documents_page(skip=30, count=30, commit=old)
            assert len(first_page) == 30
            assert len(second_page) == 20
            assert {item["@id"] for item in first_page}.isdisjoint(
                {item["@id"] for item in second_page}
            )
            requests: list[tuple[str, str, dict[str, Any] | None]] = []
            original_request = db._request

            async def recording_request(method: str, path: str, **kwargs: Any) -> Any:
                if "/api/graphql/" in path or (method == "GET" and "/api/document/" in path):
                    requests.append((method, path, kwargs.get("json")))
                return await original_request(method, path, **kwargs)

            db._request = recording_request  # type: ignore[method-assign]
            at_old = await fetch_records(db, registry, requested, revision=old)
            assert set(at_old) == {entity.id, numeric.id}
            assert isomorphic(graph_from_records([at_old[entity.id]]), graph_from_records([entity]))
            assert at_old[numeric.id] == numeric  # exact decimal lexical form
            graphql = [body for method, path, body in requests if "/api/graphql/" in path]
            assert graphql
            assert all(body is not None and "ids:" in body["query"] for body in graphql)
            entity_chunks = [
                body["query"].count("terminusdb:///data/Entity/")
                for body in graphql
                if body is not None and "Entity(ids:" in body["query"]
            ]
            assert 200 in entity_chunks
            assert max(entity_chunks) == 200
            assert all(
                "local/commit/" in path for _, path, _ in requests if "/api/graphql/" in path
            )
            assert any(
                method == "GET" and path.endswith("/local/commit/" + old.removeprefix("branch:"))
                for method, path, _ in requests
            )

            changed_properties = dict(entity.properties)
            changed_properties[SKOS + "prefLabel"] = [
                LiteralValue(lexical="Changed label", datatype=XSD + "string")
            ]
            changed = NodeRecord(id=entity.id, types=entity.types, properties=changed_properties)
            next_head = await db.replace_records(
                validate_records([changed], registry), registry, expected_head=old
            )
            latest = await fetch_records(db, registry, [entity.id], revision=next_head)
            historical = await fetch_records(db, registry, [entity.id], revision=old)
            assert isomorphic(
                graph_from_records([latest[entity.id]]), graph_from_records([changed])
            )
            assert isomorphic(
                graph_from_records([historical[entity.id]]), graph_from_records([entity])
            )
            old_page = await db.documents_page(skip=0, count=200, commit=old)
            assert any(
                item.get("canonical_iri") == entity.id and item.get("label") for item in old_page
            )

    asyncio.run(run())
