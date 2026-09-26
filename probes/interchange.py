"""M01-only JSON-LD/SHACL/TerminusDB interchange proof.

The TerminusDB document stores explicit RDF terms, not a serialized JSON-LD blob.
This deliberately narrow mapping supports IRI subjects/predicates and IRI or
literal objects; it is not the product storage model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pyshacl import validate
from rdflib import BNode, Graph, Literal, URIRef

CONTEXT_ID = "urn:c1:m01:context"
FIXTURES = Path(__file__).parent / "fixtures"


def _bundled_context() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURES / "context.jsonld").read_text(encoding="utf-8"))["@context"],
    )


def _resolve_contexts(value: Any) -> Any:
    """Replace only the declared bundled context, before RDFLib sees the input."""
    if isinstance(value, list):
        return [_resolve_contexts(item) for item in value]
    if isinstance(value, dict):
        if "@import" in value:
            raise ValueError("JSON-LD @import is unsupported; no remote contexts are allowed")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "@context":
                if item != CONTEXT_ID:
                    raise ValueError(f"JSON-LD context {item!r} is not the bundled context")
                result[key] = _bundled_context()
            else:
                result[key] = _resolve_contexts(item)
        return result
    return value


def load_jsonld(value: dict[str, Any]) -> Graph:
    if not isinstance(value, dict):
        raise ValueError("JSON-LD input must be an object")
    safe = _resolve_contexts(value)
    graph = Graph()
    graph.parse(data=json.dumps(safe), format="json-ld")
    return graph


def _validated_graph(value: dict[str, Any]) -> Graph:
    graph = load_jsonld(value)
    shapes = Graph().parse(FIXTURES / "shape.ttl", format="turtle")
    conforms, _report, details = validate(graph, shacl_graph=shapes, inference="none")
    if not conforms:
        raise ValueError(f"JSON-LD assertion violates the M01 SHACL shape: {details}")
    return graph


def to_document(value: dict[str, Any], document_id: str = "ProbeGraph/fixture") -> dict[str, Any]:
    graph = _validated_graph(value)
    triples: list[dict[str, str]] = []
    for subject, predicate, obj in graph:
        if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
            raise ValueError("M01 interchange supports only IRI subjects and predicates")
        record = {"@type": "ProbeTriple", "subject": str(subject), "predicate": str(predicate)}
        if isinstance(obj, URIRef):
            record.update(object_kind="iri", object_value=str(obj))
        elif isinstance(obj, Literal):
            record.update(object_kind="literal", object_value=str(obj))
            if obj.language:
                record["object_language"] = obj.language
            if obj.datatype:
                record["object_datatype"] = str(obj.datatype)
        elif isinstance(obj, BNode):
            raise ValueError("M01 interchange does not support blank-node objects")
        else:
            raise ValueError(f"Unsupported RDF term: {type(obj).__name__}")
        triples.append(record)
    triples.sort(key=lambda term: (term["subject"], term["predicate"], term["object_value"]))
    return {"@type": "ProbeGraph", "@id": document_id, "triples": triples}


def from_document(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("@type") != "ProbeGraph" or not isinstance(doc.get("triples"), list):
        raise ValueError("Expected a ProbeGraph document with triples")
    nodes: dict[str, dict[str, Any]] = {}
    for record in doc["triples"]:
        if not isinstance(record, dict) or record.get("@type") != "ProbeTriple":
            raise ValueError("Invalid ProbeTriple record")
        subject = record["subject"]
        predicate = record["predicate"]
        kind = record["object_kind"]
        lexical = record["object_value"]
        if not all(isinstance(term, str) for term in (subject, predicate, kind, lexical)):
            raise ValueError("RDF term fields must be strings")
        node = nodes.setdefault(subject, {"@id": subject})
        if kind == "iri":
            if "object_language" in record or "object_datatype" in record:
                raise ValueError("IRI object cannot have language or datatype")
            obj: dict[str, str] = {"@id": lexical}
        elif kind == "literal":
            obj = {"@value": lexical}
            if "object_language" in record:
                obj["@language"] = record["object_language"]
            if "object_datatype" in record:
                obj["@type"] = record["object_datatype"]
            if "@language" in obj and "@type" in obj:
                raise ValueError("Literal cannot have both language and datatype")
        else:
            raise ValueError(f"Unknown RDF object kind: {kind!r}")
        node.setdefault(predicate, []).append(obj)
    return {"@graph": list(nodes.values())}


def schema() -> list[dict[str, Any]]:
    """Small TerminusDB schema for one graph document and its owned term records."""
    optional_string = {"@type": "Optional", "@class": "xsd:string"}
    return [
        {
            "@type": "Class",
            "@id": "ProbeGraph",
            "triples": {"@type": "Set", "@class": "ProbeTriple"},
        },
        {
            "@type": "Class",
            "@id": "ProbeTriple",
            "@key": {"@type": "ValueHash"},
            "@subdocument": [],
            "subject": "xsd:string",
            "predicate": "xsd:string",
            "object_kind": "xsd:string",
            "object_value": "xsd:string",
            "object_language": optional_string,
            "object_datatype": optional_string,
        },
    ]
