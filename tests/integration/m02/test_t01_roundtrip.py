"""M02-T01: lossless supported graph through the pinned TerminusDB server."""

from __future__ import annotations

import asyncio

import pytest
from rdflib import Literal, URIRef
from rdflib.compare import isomorphic

from c1.interchange import export_jsonld, graph_from_records, import_jsonld
from c1.model.literals import SUPPORTED_DATATYPES, LiteralValue
from c1.model.profiles import ProfileRegistry
from c1.model.time import temporal_bounds
from c1.storage.terminus import StorageError
from tests.integration.m02.conftest import expected, fixture_payload, live_knowledge

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
C1 = "urn:c1:ns:core#"
PROV = "http://www.w3.org/ns/prov#"
TIME = "http://www.w3.org/2006/time#"


def _one_literal(values: list[str | LiteralValue]) -> LiteralValue:
    assert len(values) == 1
    value = values[0]
    assert isinstance(value, LiteralValue)
    return value


def test_t01_supported_roundtrip() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        batch = import_jsonld(fixture_payload(), registry)
        assert batch.records
        assert not [item for item in batch.diagnostics if item.severity == "error"]
        identities = expected("identities.json")
        expected_literals = expected("literal-values.json")
        assert {item["datatype"] for item in expected_literals} == SUPPORTED_DATATYPES

        async with live_knowledge(registry) as db:
            before = await db.head()
            committed = await db.write_records(batch, registry, expected_head=before)
            assert committed != before
            assert await db.head() == committed
            restored = await db.read_records(registry)
            assert len(restored) == len(batch.records)
            active_literal = LiteralValue(
                lexical="active", datatype="http://www.w3.org/2001/XMLSchema#string"
            )
            assert (
                sum(
                    active_literal in item.properties.get(C1 + "lifecycle", []) for item in restored
                )
                >= 3
            )
            exported = export_jsonld(restored, registry)
            assert exported == expected("canonical.jsonld")
            assert all(
                node["@id"].startswith("urn:c1:instance:dev:") for node in exported["@graph"]
            )
            assert "terminusdb:///" not in str(exported)
            reimported = import_jsonld(exported, registry)
            assert isomorphic(graph_from_records(batch.records), graph_from_records(restored))
            assert isomorphic(
                graph_from_records(batch.records), graph_from_records(reimported.records)
            )

            by_id = {record.id: record for record in restored}
            assert identities["tesla"] in by_id
            assert identities["ada"] in by_id
            assert identities["battery"] in by_id
            for entry in expected_literals:
                value = by_id[entry["assertion"]].properties[RDF + "object"]
                assert value == [
                    LiteralValue(
                        lexical=entry["lexical"],
                        datatype=entry["datatype"],
                        language=entry["language"],
                    )
                ]
                storage_key = "Assertion/" + entry["assertion"].rsplit("/", 1)[1]
                stored_document = await db.get(storage_key)
                assert stored_document is not None
                assert stored_document["object"]["literal"]["lexical"] == entry["lexical"]
                assert stored_document["object"]["literal"]["datatype"] == entry["datatype"]

            for item in expected("keywords.json")["keywords"]:
                keyword = by_id[item["id"]]
                assert keyword.properties[C1 + "keywordText"] == [
                    LiteralValue(
                        lexical=item["text"], datatype="http://www.w3.org/2001/XMLSchema#string"
                    )
                ]
                assert (
                    _one_literal(keyword.properties[C1 + "normalizedKeyword"]).lexical
                    == item["normalized"]
                )
                assert _one_literal(keyword.properties[C1 + "normalizationVersion"]).lexical == (
                    "c1-kw-1"
                )
                if item["language"] is not None:
                    assert (
                        _one_literal(keyword.properties[C1 + "keywordLanguage"]).lexical
                        == (item["language"])
                    )
                else:
                    assert C1 + "keywordLanguage" not in keyword.properties

            for interval in expected("time.json")["intervals"]:
                stored_interval = by_id[interval["id"]]
                assert stored_interval.properties[TIME + "hasBeginning"] == [
                    interval["start"]["id"]
                ]
                assert stored_interval.properties[TIME + "hasEnd"] == [interval["end"]["id"]]
                for side in ("start", "end"):
                    expectation = interval[side]
                    boundary = by_id[expectation["id"]]
                    assert (
                        _one_literal(boundary.properties[C1 + "boundaryState"]).lexical
                        == (expectation["state"])
                    )
                    time_values = [
                        value
                        for predicate, values in boundary.properties.items()
                        if predicate.startswith(TIME + "inXSD")
                        for value in values
                    ]
                    if expectation["state"] == "known":
                        boundary_value = _one_literal(time_values)
                        assert boundary_value.lexical == expectation["lexical"]
                        assert boundary_value.datatype == expectation["datatype"]
                        earliest, latest, unknown_timezone = temporal_bounds(
                            boundary_value.lexical, boundary_value.datatype
                        )
                        assert (earliest, latest, unknown_timezone) == (
                            expectation["earliest"],
                            expectation["latest"],
                            expectation["timezone_unknown"],
                        )
                    else:
                        assert time_values == []

            graph = graph_from_records(restored)
            first_claim = URIRef(identities["revenue_assertions"][0])
            assert (
                first_claim,
                URIRef(PROV + "wasGeneratedBy"),
                URIRef(identities["activities"][0]),
            ) in graph
            assert (first_claim, URIRef(C1 + "evidence"), None) in graph
            assert (
                URIRef("urn:c1:instance:dev:boundary/00000001-0000-4000-8000-000000000000"),
                URIRef(TIME + "inXSDgYear"),
                Literal(
                    "2020",
                    datatype=URIRef("http://www.w3.org/2001/XMLSchema#gYear"),
                    normalize=False,
                ),
            ) in graph

            with pytest.raises(StorageError, match="C1-ST-001"):
                await db.install_profile(registry)
            assert await db.head() == committed

    asyncio.run(run())
