"""Lossless RDF node to typed TerminusDB document mapping.

The backend ID, schema field names, and numeric projections are storage
details. ``canonical_iri`` and LiteralValue's lexical fields are authoritative.
Unrepresentable backend date/double shadows are omitted with an explicit
``projection_status``; reads reconstruct only from lexical fields. Set-valued
properties are unordered, as in RDF, so source list order is not retained.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from c1.model.ids import KINDS, validate_iri
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry, PropertyDefinition
from c1.model.time import TEMPORAL_TYPES, temporal_bounds
from c1.storage.terminus import StorageError

_XSD = "http://www.w3.org/2001/XMLSchema#"
_RDF_LANG = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
_RDFS_LITERAL = "http://www.w3.org/2000/01/rdf-schema#Literal"
_UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_OUT_OF_RANGE = "out_of_backend_date_range"
_NONFINITE = "nonfinite_double"
_FLOAT_OUT_OF_RANGE = "out_of_backend_double_range"
_INTERNAL_METADATA = re.compile(r"urn:c1:internal:installed-profile:[a-z][A-Za-z0-9-]*\Z")
_CANONICAL_CLASS_KINDS = {
    "Entity": "entity",
    "Assertion": "assertion",
    "Source": "source",
    "Evidence": "evidence",
    "Activity": "activity",
    "ResolutionRecord": "resolution",
    "Document": "document",
    "DocumentPart": "part",
    "ChangeSet": "changeset",
}


def installed_profile_iri(profile_name: str) -> str:
    if not re.fullmatch(r"[a-z][A-Za-z0-9-]*", profile_name):
        raise ValueError("invalid profile name")
    return f"urn:c1:internal:installed-profile:{profile_name}"


def reject_reserved_id(iri: str) -> None:
    """Keep persisted installation markers outside caller supplied RDF data."""
    if _INTERNAL_METADATA.fullmatch(iri):
        raise StorageError("C1-ST-004", "internal profile marker IRI is reserved")


def _value_kind(definition: PropertyDefinition) -> str:
    literals = any(
        value.startswith(_XSD) or value in {_RDF_LANG, _RDFS_LITERAL} for value in definition.ranges
    )
    iris = any(
        value == "@id" or (not value.startswith(_XSD) and value not in {_RDF_LANG, _RDFS_LITERAL})
        for value in definition.ranges
    )
    if literals and iris:
        return "mixed"
    return "literal" if literals else "iri"


def storage_id(record: NodeRecord, class_definition: ClassDefinition, instance_base: str) -> str:
    """Map canonical UUID IDs directly; hash other named, independent RDF nodes."""
    validate_iri(record.id)
    if record.id.startswith(instance_base):
        tail = record.id[len(instance_base) :]
        kind, slash, suffix = tail.partition("/")
        if kind in KINDS:
            if not slash or not _UUID4.fullmatch(suffix):
                raise StorageError("C1-ST-004", "canonical ID needs a UUIDv4 suffix")
            expected_kind = _CANONICAL_CLASS_KINDS.get(class_definition.storage_name)
            if expected_kind is not None and kind != expected_kind:
                raise StorageError("C1-ST-004", "canonical ID kind conflicts with its class")
            parsed = UUID(suffix)
            if parsed.version == 4:
                return f"{class_definition.storage_name}/{suffix}"
            raise StorageError("C1-ST-004", "canonical ID needs a UUIDv4 suffix")
    digest = hashlib.sha256(record.id.encode("utf-8")).hexdigest()
    return f"{class_definition.storage_name}/{digest}"


def _projection(literal: LiteralValue) -> dict[str, Any]:
    lexical = " ".join(literal.lexical.split())
    datatype = literal.datatype
    if datatype == _XSD + "integer":
        return {"value_integer": lexical}
    if datatype == _XSD + "decimal":
        return {"value_decimal": lexical}
    if datatype == _XSD + "boolean":
        return {"value_boolean": lexical in {"true", "1"}}
    if datatype == _XSD + "double":
        if lexical in {"INF", "-INF", "NaN"}:
            return {"projection_status": _NONFINITE}
        number = float(lexical)
        if number in (float("inf"), float("-inf")):
            return {"projection_status": _FLOAT_OUT_OF_RANGE}
        if number == 0 and Decimal(lexical) != 0:
            return {"projection_status": _FLOAT_OUT_OF_RANGE}
        return {"value_double": number}
    if datatype in TEMPORAL_TYPES:
        earliest, latest, timezone_unknown = temporal_bounds(lexical, datatype)
        # The pinned backend dateTime parser must not silently constrain the
        # full XSD value space. Preserve the exact value and flag this case.
        years: list[int] = []
        for value in (earliest, latest):
            year_match = re.match(r"(-?\d+)-", value)
            if year_match is None:
                raise StorageError("C1-ST-004", "temporal bounds have invalid years")
            years.append(int(year_match[1]))
        if any(year < 1 or year > 9999 for year in years):
            return {"projection_status": _OUT_OF_RANGE, "timezone_unknown": timezone_unknown}
        return {
            "value_earliest": earliest,
            "value_latest": latest,
            "timezone_unknown": timezone_unknown,
        }
    return {}


def _literal_document(literal: LiteralValue) -> dict[str, Any]:
    value: dict[str, Any] = {
        "@type": "LiteralValue",
        "lexical": literal.lexical,
        "datatype": literal.datatype,
    }
    if literal.language is not None:
        value["language"] = literal.language
    try:
        value.update(_projection(literal))
    except (ValueError, OverflowError) as exc:
        raise StorageError("C1-ST-004", "validated literal cannot be projected") from exc
    return value


def _encode_value(value: str | LiteralValue, definition: PropertyDefinition) -> Any:
    kind = _value_kind(definition)
    if kind == "iri":
        if not isinstance(value, str):
            raise StorageError("C1-ST-004", "literal supplied for IRI field")
        return validate_iri(value)
    if kind == "literal":
        if not isinstance(value, LiteralValue):
            raise StorageError("C1-ST-004", "IRI supplied for literal field")
        return _literal_document(value)
    if isinstance(value, str):
        return {"@type": "Value", "iri": validate_iri(value)}
    return {"@type": "Value", "literal": _literal_document(value)}


def record_to_document(
    record: NodeRecord, registry: ProfileRegistry, instance_base: str
) -> dict[str, Any]:
    class_definition = registry.primary_class(record.types)
    result: dict[str, Any] = {
        "@id": storage_id(record, class_definition, instance_base),
        "@type": class_definition.storage_name,
        "canonical_iri": record.id,
        "types": sorted(record.types),
    }
    for predicate, values in sorted(record.properties.items()):
        definition = class_definition.properties.get(predicate)
        if definition is None:
            raise StorageError("C1-ST-004", "record contains a field absent from its storage class")
        encoded = [_encode_value(value, definition) for value in values]
        if definition.max_count == 1:
            if len(encoded) > 1:
                raise StorageError("C1-ST-004", "single-valued field has multiple values")
            if encoded:
                result[definition.name] = encoded[0]
        else:
            # Sets are unordered by contract. Canonical ordering makes raw
            # backend documents stable without changing the RDF value set.
            result[definition.name] = sorted(encoded, key=repr)
    return result


def records_to_documents(
    records: Iterable[NodeRecord], registry: ProfileRegistry, instance_base: str
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for record in records:
        reject_reserved_id(record.id)
        document = record_to_document(record, registry, instance_base)
        prior = ids.setdefault(document["@id"], record.id)
        if prior != record.id:
            raise StorageError("C1-ST-004", "storage ID collision between canonical IRIs")
        if prior == record.id and any(item["@id"] == document["@id"] for item in documents):
            raise StorageError("C1-ST-004", "duplicate storage ID in one batch")
        documents.append(document)
    return documents


def _literal_from_document(value: Any) -> LiteralValue:
    if not isinstance(value, dict) or value.get("@type") != "LiteralValue":
        raise StorageError("C1-ST-005", "stored literal has the wrong type")
    lexical = value.get("lexical")
    datatype = value.get("datatype")
    language = value.get("language")
    if not isinstance(lexical, str) or not isinstance(datatype, str):
        raise StorageError("C1-ST-005", "stored literal lacks lexical fields")
    if language is not None and not isinstance(language, str):
        raise StorageError("C1-ST-005", "stored literal has an invalid language")
    return LiteralValue(lexical=lexical, datatype=datatype, language=language)


def _decode_value(value: Any, definition: PropertyDefinition) -> str | LiteralValue:
    kind = _value_kind(definition)
    if kind == "iri":
        if not isinstance(value, str):
            raise StorageError("C1-ST-005", "stored IRI field is not text")
        return validate_iri(value)
    if kind == "literal":
        return _literal_from_document(value)
    if not isinstance(value, dict) or value.get("@type") != "Value":
        raise StorageError("C1-ST-005", "stored mixed value has the wrong type")
    if ("iri" in value) == ("literal" in value):
        raise StorageError("C1-ST-005", "stored mixed value must choose one representation")
    if "iri" in value:
        iri = value["iri"]
        if not isinstance(iri, str):
            raise StorageError("C1-ST-005", "stored mixed IRI is not text")
        return validate_iri(iri)
    return _literal_from_document(value["literal"])


def document_to_record(document: dict[str, Any], registry: ProfileRegistry) -> NodeRecord:
    storage_name = document.get("@type")
    matches = [item for item in registry.classes.values() if item.storage_name == storage_name]
    if len(matches) != 1:
        raise StorageError("C1-ST-005", "stored document has an unknown class")
    class_definition = matches[0]
    canonical_iri = document.get("canonical_iri")
    types = document.get("types")
    if (
        not isinstance(canonical_iri, str)
        or not isinstance(types, list)
        or not all(isinstance(item, str) for item in types)
    ):
        raise StorageError("C1-ST-005", "stored record lacks canonical identity")
    if class_definition.iri not in types:
        raise StorageError("C1-ST-005", "stored record class conflicts with declared RDF type")
    properties: dict[str, list[str | LiteralValue]] = {}
    known_fields = {"@id", "@type", "canonical_iri", "types"}
    for predicate, definition in class_definition.properties.items():
        known_fields.add(definition.name)
        if definition.name not in document:
            continue
        raw = document[definition.name]
        values = [raw] if definition.max_count == 1 else raw
        if not isinstance(values, list):
            raise StorageError("C1-ST-005", "stored multivalued field is not a list")
        properties[predicate] = [_decode_value(value, definition) for value in values]
    if set(document) - known_fields:
        raise StorageError("C1-ST-005", "stored record contains undeclared fields")
    return NodeRecord(id=validate_iri(canonical_iri), types=types, properties=properties)


def documents_to_records(
    documents: Iterable[dict[str, Any]],
    registry: ProfileRegistry,
    instance_base: str,
    *,
    include_metadata: bool = False,
) -> list[NodeRecord]:
    records: list[NodeRecord] = []
    seen: set[str] = set()
    for document in documents:
        canonical = document.get("canonical_iri")
        if (
            document.get("@type") == "SchemaProfile"
            and isinstance(canonical, str)
            and _INTERNAL_METADATA.fullmatch(canonical)
            and not include_metadata
        ):
            continue
        record = document_to_record(document, registry)
        class_definition = registry.primary_class(record.types)
        if storage_id(record, class_definition, instance_base) != document.get("@id"):
            raise StorageError("C1-ST-005", "stored ID does not match canonical identity")
        if record.id in seen:
            raise StorageError("C1-ST-005", "duplicate canonical identity in storage")
        seen.add(record.id)
        records.append(record)
    return records
