"""M02-T02: record and SHACL structure, and independent claims."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from c1.interchange import graph_from_records, import_jsonld, validate_shacl
from c1.model.diagnostics import ProfileError
from c1.model.literals import LiteralValue
from c1.model.profiles import ProfileRegistry
from c1.model.records import AssertionRecord, EntityRecord

CONTEXT = "urn:c1:ns:core:context:1"
BASE = "urn:c1:instance:dev:"
C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"


def entity(label: str = "Ada") -> dict[str, Any]:
    return {
        "@id": BASE + "entity/00000000-0000-4000-8000-000000000001",
        "@type": "Entity",
        "label": {"@value": label, "@language": "en"},
        "lifecycle": "active",
    }


def manual_assertion(suffix: str, obj: dict[str, str]) -> dict[str, Any]:
    return {
        "@id": BASE + f"assertion/{suffix}",
        "@type": "Assertion",
        "subject": {"@id": entity()["@id"]},
        "predicate": {"@id": C1 + "revenue"},
        "object": obj,
        "origin": "manual",
        "reviewState": "reported",
        "lifecycle": "active",
        "manualStatement": {"@value": "true", "@type": "xsd:boolean"},
        "wasAttributedTo": {"@id": BASE + "agent/reviewer"},
    }


def code(exc: pytest.ExceptionInfo[ProfileError]) -> str:
    return exc.value.diagnostics[0].code


def test_missing_label_fails_record_layer_and_shacl() -> None:
    with pytest.raises(ValidationError):
        EntityRecord(id=entity()["@id"], labels=[])
    malformed = entity()
    del malformed["label"]
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [malformed]})
    assert code(caught) == "C1-IX-030"
    graph = Graph()
    graph.add((URIRef(malformed["@id"]), RDF.type, URIRef(C1 + "Entity")))
    with pytest.raises(ProfileError) as shacl:
        validate_shacl(graph, ProfileRegistry())
    assert code(shacl) == "C1-IX-030"


def test_assertion_missing_subject_and_wrong_range_rejected() -> None:
    missing = manual_assertion("one", {"@value": "42.5000", "@type": "xsd:decimal"})
    del missing["subject"]
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [entity(), missing]})
    assert code(caught) == "C1-IX-030"
    graph = Graph()
    claim = URIRef(missing["@id"])
    graph.add((claim, RDF.type, URIRef(C1 + "Assertion")))
    graph.add((claim, RDF.predicate, URIRef(C1 + "revenue")))
    graph.add((claim, RDF.object, Literal("42.5000", datatype=URIRef(XSD + "decimal"))))
    for name, value in (
        ("origin", "manual"),
        ("reviewState", "reported"),
        ("lifecycle", "active"),
    ):
        graph.add((claim, URIRef(C1 + name), Literal(value)))
    with pytest.raises(ProfileError) as shacl:
        validate_shacl(graph, ProfileRegistry())
    assert code(shacl) == "C1-IX-030"
    wrong = entity()
    wrong["label"] = {"@value": "7", "@type": "xsd:integer"}
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [wrong]})
    assert code(caught) == "C1-IX-030"
    wrong_graph = Graph()
    subject = URIRef(wrong["@id"])
    wrong_graph.add((subject, RDF.type, URIRef(C1 + "Entity")))
    wrong_graph.add(
        (subject, URIRef(SKOS + "prefLabel"), Literal(7, datatype=URIRef(XSD + "integer")))
    )
    wrong_graph.add((subject, URIRef(C1 + "lifecycle"), Literal("active")))
    with pytest.raises(ProfileError) as shacl:
        validate_shacl(wrong_graph, ProfileRegistry())
    assert code(shacl) == "C1-IX-030"


def test_literal_language_and_datatype_conflict() -> None:
    malformed = entity()
    malformed["label"] = {"@value": "Ada", "@language": "en", "@type": "xsd:string"}
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [malformed]})
    assert code(caught) == "C1-IX-022"


def test_conflicting_claims_and_two_employments_remain_separate() -> None:
    first = manual_assertion("one", {"@value": "42.5000", "@type": "xsd:decimal"})
    second = manual_assertion("two", {"@value": "43.0000", "@type": "xsd:decimal"})
    third = manual_assertion("three", {"@id": BASE + "entity/employer-a"})
    fourth = manual_assertion("four", {"@id": BASE + "entity/employer-b"})
    third["predicate"] = {"@id": C1 + "worksFor"}
    fourth["predicate"] = {"@id": C1 + "worksFor"}
    batch = import_jsonld({"@context": CONTEXT, "@graph": [entity(), first, second, third, fourth]})
    assert len(batch.records) == 5
    graph = graph_from_records(batch.records)
    assert (
        URIRef(first["@id"]),
        URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#object"),
        Literal("42.5000", datatype=URIRef(XSD + "decimal"), normalize=False),
    ) in graph
    assert len({item.id for item in batch.records}) == 5


def test_unattributed_manual_and_unattributed_confidence_rejected() -> None:
    statement = manual_assertion("one", {"@value": "1", "@type": "xsd:integer"})
    del statement["wasAttributedTo"]
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [entity(), statement]})
    assert code(caught) == "C1-IX-030"
    statement["wasAttributedTo"] = {"@id": BASE + "agent/reviewer"}
    statement["confidence"] = {"@value": "0.75", "@type": "xsd:decimal"}
    with pytest.raises(ProfileError) as caught:
        import_jsonld({"@context": CONTEXT, "@graph": [entity(), statement]})
    assert code(caught) == "C1-IX-030"


def test_record_models_preserve_lexical_and_provenance_fields() -> None:
    assertion = AssertionRecord(
        id=BASE + "assertion/model",
        subject=entity()["@id"],
        predicate=C1 + "revenue",
        object=LiteralValue(lexical="42.5000", datatype=XSD + "decimal"),
        origin="manual",
        attributed_to=BASE + "agent/reviewer",
        manual_statement=True,
    )
    node = assertion.to_node()
    assert node.properties["http://www.w3.org/1999/02/22-rdf-syntax-ns#object"][0] == (
        assertion.object
    )
    assert node.properties[C1 + "manualStatement"][0] == LiteralValue(
        lexical="true", datatype=XSD + "boolean"
    )
