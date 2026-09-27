"""M02-T01: canonical export retains RDF term identities and lexical values."""

from __future__ import annotations

from typing import Any

import pytest
from rdflib import Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF

from c1.interchange import NodeRecord, export_jsonld, graph_from_records, import_jsonld
from c1.model.diagnostics import ProfileError
from c1.model.literals import LiteralValue

CONTEXT = "urn:c1:ns:core:context:1"
BASE = "urn:c1:instance:dev:"
C1 = "urn:c1:ns:core#"


def test_export_is_deterministic_and_round_trips() -> None:
    payload: dict[str, Any] = {
        "@context": CONTEXT,
        "@graph": [
            {
                "@id": BASE + "entity/one",
                "@type": "Entity",
                "label": {"@value": "Müller", "@language": "DE"},
                "lifecycle": "active",
            },
            {
                "@id": BASE + "assertion/one",
                "@type": ["Assertion", "rdf:Statement"],
                "subject": BASE + "entity/one",
                "predicate": C1 + "revenue",
                "object": {"@value": "42.5000", "@type": "xsd:decimal"},
                "origin": "manual",
                "reviewState": "reported",
                "lifecycle": "active",
                "manualStatement": True,
                "wasAttributedTo": BASE + "agent/reviewer",
            },
        ],
    }
    imported = import_jsonld(payload)
    exported = export_jsonld(imported.records)
    restored = import_jsonld(exported)
    assert exported == export_jsonld(reversed(imported.records))
    assert isomorphic(graph_from_records(imported.records), graph_from_records(restored.records))
    assertion = URIRef(BASE + "assertion/one")
    assert (assertion, RDF.type, RDF.Statement) in graph_from_records(restored.records)
    assert (
        assertion,
        RDF.object,
        Literal(
            "42.5000", datatype=URIRef("http://www.w3.org/2001/XMLSchema#decimal"), normalize=False
        ),
    ) in graph_from_records(restored.records)
    assert any(
        value.get("@language") == "de"
        for node in exported["@graph"]
        for values in node.values()
        if isinstance(values, list)
        for value in values
        if isinstance(value, dict)
    )


def test_native_values_and_bundled_node_context_are_supported() -> None:
    assertions = [
        {
            "@context": CONTEXT,
            "@id": BASE + f"assertion/{index}",
            "@type": "Assertion",
            "subject": BASE + "entity/one",
            "predicate": "rdf:value",
            "object": item,
            "origin": "manual",
            "reviewState": "reported",
            "lifecycle": "active",
            "manualStatement": True,
            "wasAttributedTo": BASE + "agent/reviewer",
        }
        for index, item in enumerate((True, 7, 2.5))
    ]
    payload = {
        "@context": CONTEXT,
        "@graph": [
            {
                "@context": CONTEXT,
                "@id": BASE + "entity/one",
                "@type": "Entity",
                "label": "Ada",
                "lifecycle": "active",
            },
            *assertions,
        ],
    }
    batch = import_jsonld(payload)
    lexical = {
        value.lexical: value.datatype.rsplit("#", 1)[-1]
        for record in batch.records[1:]
        for value in record.properties["http://www.w3.org/1999/02/22-rdf-syntax-ns#object"]
        if not isinstance(value, str)
    }
    assert lexical == {"true": "boolean", "7": "integer", "2.5": "double"}


def test_keyword_coalescing_keeps_first_original_spelling() -> None:
    payload = {
        "@context": CONTEXT,
        "@graph": [
            {
                "@id": BASE + "entity/one",
                "@type": "Entity",
                "label": "Ada",
                "lifecycle": "active",
                "keyword": [BASE + "keyword/one", BASE + "keyword/two"],
            },
            {
                "@id": BASE + "keyword/one",
                "@type": "Keyword",
                "keywordText": "Ｂａｔｔｅｒｙ",
                "keywordLanguage": "EN",
            },
            {
                "@id": BASE + "keyword/two",
                "@type": "Keyword",
                "keywordText": "battery",
                "keywordLanguage": "en",
            },
        ],
    }
    batch = import_jsonld(payload)
    assert [item.code for item in batch.diagnostics] == ["C1-IX-041"]
    assert [item.id for item in batch.records] == [BASE + "entity/one", BASE + "keyword/one"]
    keyword = batch.records[1]
    original = keyword.properties[C1 + "keywordText"][0]
    normalized = keyword.properties[C1 + "normalizedKeyword"][0]
    assert isinstance(original, LiteralValue) and original.lexical == "Ｂａｔｔｅｒｙ"
    assert isinstance(normalized, LiteralValue) and normalized.lexical == "battery"


def test_coalesced_keyword_with_other_reference_is_not_dropped() -> None:
    payload = {
        "@context": CONTEXT,
        "@graph": [
            {
                "@id": BASE + "entity/one",
                "@type": "Entity",
                "label": "Ada",
                "lifecycle": "active",
                "keyword": [BASE + "keyword/one", BASE + "keyword/two"],
            },
            {
                "@id": BASE + "keyword/one",
                "@type": "Keyword",
                "keywordText": "Battery",
            },
            {
                "@id": BASE + "keyword/two",
                "@type": "Keyword",
                "keywordText": "battery",
            },
            {
                "@id": BASE + "activity/one",
                "@type": "Activity",
                "wasAttributedTo": BASE + "agent/reviewer",
                "used": BASE + "keyword/two",
            },
        ],
    }
    batch = import_jsonld(payload)
    assert {record.id for record in batch.records} == {
        BASE + "entity/one",
        BASE + "keyword/one",
        BASE + "keyword/two",
        BASE + "activity/one",
    }
    entity = next(record for record in batch.records if record.id == BASE + "entity/one")
    assert entity.properties[C1 + "keyword"] == [BASE + "keyword/one"]
    assert [item.code for item in batch.diagnostics] == ["C1-IX-041"]


def test_export_revalidates_caller_constructed_nodes() -> None:
    unvalidated = NodeRecord(
        id=BASE + "entity/one",
        types=[C1 + "Entity"],
        properties={
            "http://www.w3.org/2004/02/skos/core#prefLabel": [
                LiteralValue(lexical="Ada", datatype="http://www.w3.org/2001/XMLSchema#string")
            ],
            C1 + "lifecycle": [
                LiteralValue(lexical="active", datatype="http://www.w3.org/2001/XMLSchema#string")
            ],
            "urn:unknown:predicate": [
                LiteralValue(lexical="hidden", datatype="http://www.w3.org/2001/XMLSchema#string")
            ],
        },
    )
    with pytest.raises(ProfileError) as caught:
        export_jsonld([unvalidated])
    assert caught.value.diagnostics[0].code == "C1-IX-011"
