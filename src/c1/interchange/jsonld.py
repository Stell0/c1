"""A deliberately bounded JSON-LD 1.1 interchange profile.

Input is interpreted only after its context identifier has been matched to a
bundled profile.  This module never invokes a JSON-LD remote document loader.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, XSD

from c1.model.diagnostics import Diagnostic, ProfileError, fail
from c1.model.ids import validate_iri
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord, ValidatedBatch
from c1.model.profiles import ProfileRegistry

CORE_CONTEXT = "urn:c1:ns:core:context:1"
_REJECTED = frozenset({"@import", "@included", "@nest", "@reverse", "@list", "@index", "@json"})
_NODE_KEYWORDS = frozenset({"@id", "@type", "@context"})
_LITERAL_KEYWORDS = frozenset({"@value", "@type", "@language"})
_XSD = str(XSD)
_C1 = "urn:c1:ns:core#"
_SKOS_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"


def _is_absolute(value: str) -> bool:
    head, sep, _tail = value.partition(":")
    return bool(sep and head and head[0].isalpha() and all(c.isalnum() or c in "+-." for c in head))


def _context_map(registry: ProfileRegistry, identifier: str) -> dict[str, Any]:
    document = registry.contexts.get(identifier)
    if document is None:
        fail("C1-IX-001", f"Context is not bundled: {identifier}", "@context")
    context = document.get("@context")
    if not isinstance(context, dict):
        fail("C1-PR-001", "Bundled context must be an object", identifier)
    return context


def _expand(term: str, context: Mapping[str, Any]) -> str:
    definition = context.get(term)
    if isinstance(definition, str):
        return _expand(definition, {key: value for key, value in context.items() if key != term})
    if isinstance(definition, dict):
        value = definition.get("@id")
        if isinstance(value, str):
            return _expand(value, {key: val for key, val in context.items() if key != term})
    prefix, sep, suffix = term.partition(":")
    if sep:
        prefix_def = context.get(prefix)
        if isinstance(prefix_def, str) and prefix_def != term:
            return prefix_def + suffix
        if isinstance(prefix_def, dict):
            prefix_iri = prefix_def.get("@id")
            if isinstance(prefix_iri, str):
                return prefix_iri + suffix
    if _is_absolute(term):
        return term
    fail("C1-IX-011", f"Undeclared term: {term}", term)


def _reject_keywords(value: Any, path: str = "$") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_keywords(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _REJECTED:
                fail("C1-IX-002", f"Unsupported JSON-LD keyword {key}", f"{path}.{key}")
            if key == "@context":
                if not isinstance(item, str):
                    fail(
                        "C1-IX-001",
                        "Inline or composite contexts are unsupported",
                        f"{path}.@context",
                    )
                continue
            _reject_keywords(item, f"{path}.{key}")


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, dict) and "@set" in value:
        if set(value) != {"@set"} or not isinstance(value["@set"], list):
            fail("C1-IX-030", "@set must contain only an array", "@set")
        return value["@set"]
    if isinstance(value, list):
        return value
    return [value]


def _lexical(value: Any, path: str) -> tuple[str, str]:
    if isinstance(value, str):
        return value, _XSD + "string"
    if isinstance(value, bool):
        return ("true" if value else "false"), _XSD + "boolean"
    if isinstance(value, int):
        return str(value), _XSD + "integer"
    if isinstance(value, float) and math.isfinite(value):
        return repr(value), _XSD + "double"
    fail("C1-IX-020", "Literal value must be text, boolean, integer, or finite float", path)


def _literal(value: dict[str, Any], context: Mapping[str, Any], path: str) -> LiteralValue:
    if not set(value).issubset(_LITERAL_KEYWORDS) or "@value" not in value:
        fail("C1-IX-030", "Malformed literal object", path)
    lexical, inferred_datatype = _lexical(value["@value"], path)
    language = value.get("@language")
    datatype = value.get("@type", "rdf:langString" if language is not None else inferred_datatype)
    if language is not None and "@type" in value:
        fail("C1-IX-022", "A literal cannot have both language and datatype", path)
    if not isinstance(datatype, str) or (language is not None and not isinstance(language, str)):
        fail("C1-IX-020", "Invalid literal datatype or language", path)
    try:
        return LiteralValue(lexical=lexical, datatype=_expand(datatype, context), language=language)
    except ValidationError as exc:
        error = exc.errors()[0]
        fail(str(error["type"]), str(error["msg"]), path)


def _value(
    value: Any, context: Mapping[str, Any], path: str, definition: Any = None
) -> str | LiteralValue:
    if isinstance(value, dict):
        if "@id" in value:
            if set(value) != {"@id"} or not isinstance(value["@id"], str):
                fail("C1-IX-030", "IRI object must contain only @id", path)
            if value["@id"].startswith("_:"):
                fail("C1-IX-010", "Blank nodes are unsupported", path)
            iri = _expand(value["@id"], context)
            if iri.startswith("_:"):
                fail("C1-IX-010", "Blank nodes are unsupported", path)
            return iri
        return _literal(value, context, path)
    coercion = definition.get("@type") if isinstance(definition, dict) else None
    if isinstance(value, str) and coercion in {"@id", "@vocab"}:
        iri = _expand(value, context)
        if iri.startswith("_:"):
            fail("C1-IX-010", "Blank nodes are unsupported", path)
        return iri
    lexical, inferred_datatype = _lexical(value, path)
    language = definition.get("@language") if isinstance(definition, dict) else None
    if language is not None:
        if not isinstance(language, str):
            fail("C1-IX-022", "Invalid default language tag", path)
        datatype = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
    elif isinstance(coercion, str) and coercion not in {"@id", "@vocab"}:
        datatype = _expand(coercion, context)
    else:
        datatype = inferred_datatype
    try:
        return LiteralValue(lexical=lexical, datatype=datatype, language=language)
    except ValidationError as exc:
        error = exc.errors()[0]
        fail(str(error["type"]), str(error["msg"]), path)


def _node(
    value: Any, context: Mapping[str, Any], path: str, registry: ProfileRegistry
) -> NodeRecord:
    if not isinstance(value, dict):
        fail("C1-IX-030", "Graph node must be an object", path)
    local_context = context
    if "@context" in value:
        identifier = value["@context"]
        if not isinstance(identifier, str):
            fail("C1-IX-001", "Inline or composite contexts are unsupported", f"{path}.@context")
        local_context = _context_map(registry, identifier)
    identifier = value.get("@id")
    if not isinstance(identifier, str):
        fail("C1-IX-010", "Every node needs an IRI @id", f"{path}.@id")
    if identifier.startswith("_:"):
        fail("C1-IX-010", "Blank nodes are unsupported", f"{path}.@id")
    iri = _expand(identifier, local_context)
    if not _is_absolute(iri):
        fail("C1-IX-010", "Node @id must be an absolute IRI", f"{path}.@id")
    raw_types = _sequence(value.get("@type", []))
    if not raw_types or any(not isinstance(item, str) for item in raw_types):
        fail("C1-IX-012", "Every node needs a declared @type", f"{path}.@type")
    types = [_expand(item, local_context) for item in raw_types]
    properties: dict[str, list[str | LiteralValue]] = {}
    for key, raw in value.items():
        if key in _NODE_KEYWORDS:
            continue
        if key.startswith("@"):
            fail("C1-IX-002", f"Unsupported JSON-LD keyword {key}", f"{path}.{key}")
        predicate = _expand(key, local_context)
        if predicate in properties:
            fail("C1-IX-030", "Predicate appears through multiple aliases", f"{path}.{key}")
        properties[predicate] = [
            _value(item, local_context, f"{path}.{key}[{index}]", local_context.get(key))
            for index, item in enumerate(_sequence(raw))
        ]
    return NodeRecord(id=iri, types=types, properties=properties)


def _validate_record(record: NodeRecord, registry: ProfileRegistry) -> None:
    try:
        class_definition = registry.primary_class(record.types)
    except ProfileError as exc:
        fail("C1-IX-012", str(exc), record.id)
    for predicate, definition in class_definition.properties.items():
        values = record.properties.get(predicate, [])
        if len(values) < definition.min_count:
            fail("C1-IX-030", f"Missing required predicate {predicate}", record.id)
        if definition.max_count is not None and len(values) > definition.max_count:
            fail("C1-IX-030", f"Too many values for {predicate}", record.id)
    for predicate, values in record.properties.items():
        if predicate not in registry.predicates:
            fail("C1-IX-011", f"Undeclared predicate {predicate}", record.id)
        if predicate not in class_definition.properties:
            fail("C1-IX-011", f"Predicate {predicate} is not allowed on this class", record.id)
        definition = class_definition.properties[predicate]
        for value in values:
            if isinstance(value, str):
                if not _is_absolute(value):
                    fail("C1-IX-010", "Object must be an absolute IRI", record.id)
                if not any(item == "@id" or item in registry.classes for item in definition.ranges):
                    fail("C1-IX-030", f"IRI is outside range of {predicate}", record.id)
            elif (
                value.datatype not in definition.ranges
                and "http://www.w3.org/2000/01/rdf-schema#Literal" not in definition.ranges
            ):
                fail("C1-IX-030", f"Literal datatype is outside range of {predicate}", record.id)
            if definition.enum:
                lexical = value if isinstance(value, str) else value.lexical
                if lexical not in definition.enum:
                    fail("C1-IX-030", f"Value is outside enum of {predicate}", record.id)


def _semantic_assertion(record: NodeRecord, registry: ProfileRegistry) -> None:
    if _C1 + "Assertion" not in record.types:
        return
    predicate_values = record.properties.get(str(RDF.predicate), [])
    object_values = record.properties.get(str(RDF.object), [])
    if len(predicate_values) == 1 and isinstance(predicate_values[0], str):
        claim_predicate = predicate_values[0]
        claim_definition = registry.predicates.get(claim_predicate)
        if claim_definition is None:
            fail("C1-IX-011", f"Claim predicate is undeclared: {claim_predicate}", record.id)
        if len(object_values) == 1:
            claim_object = object_values[0]
            if isinstance(claim_object, str):
                allowed = "@id" in claim_definition.ranges or any(
                    item in registry.classes for item in claim_definition.ranges
                )
            else:
                allowed = (
                    claim_object.datatype in claim_definition.ranges
                    or "http://www.w3.org/2000/01/rdf-schema#Literal" in claim_definition.ranges
                )
            if not allowed:
                fail("C1-IX-030", "Claim object is outside predicate range", record.id)
    evidence = record.properties.get(_C1 + "evidence", [])
    manual = record.properties.get(_C1 + "manualStatement", [])
    manual_true = any(
        isinstance(value, LiteralValue) and value.lexical in {"true", "1"} for value in manual
    )
    attributed = record.properties.get("http://www.w3.org/ns/prov#wasAttributedTo", [])
    if manual_true and not attributed:
        fail("C1-IX-030", "Manual statements need actor attribution", record.id)
    if not evidence and not (manual_true and attributed):
        fail(
            "C1-IX-030",
            "An assertion needs source evidence or an attributed manual statement",
            record.id,
        )
    if record.properties.get(_C1 + "confidence") and not (
        record.properties.get(_C1 + "confidenceMethod") and attributed
    ):
        fail("C1-IX-030", "Confidence needs a method and attribution", record.id)


def _canonicalize(records: list[NodeRecord]) -> tuple[list[NodeRecord], list[Diagnostic]]:
    from c1.model.keywords import Keyword

    canonical: list[NodeRecord] = []
    diagnostics: list[Diagnostic] = []
    keyword_nodes: dict[str, NodeRecord] = {}
    for record in records:
        if _C1 + "Keyword" not in record.types:
            canonical.append(record)
            continue
        text_values = record.properties.get(_C1 + "keywordText", [])
        language_values = record.properties.get(_C1 + "keywordLanguage", [])
        if len(text_values) != 1 or not isinstance(text_values[0], LiteralValue):
            fail("C1-IX-030", "Keyword needs exactly one lexical text", record.id)
        if len(language_values) > 1 or any(
            not isinstance(value, LiteralValue) for value in language_values
        ):
            fail("C1-IX-030", "Keyword language must be a single literal", record.id)
        language = (
            language_values[0].lexical
            if language_values and isinstance(language_values[0], LiteralValue)
            else None
        )
        try:
            keyword = Keyword(text=text_values[0].lexical, language=language)
        except ValidationError as exc:
            error = exc.errors()[0]
            fail(str(error["type"]), str(error["msg"]), record.id)
        properties = dict(record.properties)
        normalized = properties.get(_C1 + "normalizedKeyword", [])
        version = properties.get(_C1 + "normalizationVersion", [])
        if normalized and (
            len(normalized) != 1
            or not isinstance(normalized[0], LiteralValue)
            or normalized[0].lexical != keyword.normalized
        ):
            fail("C1-IX-030", "Stored keyword normalization disagrees with c1-kw-1", record.id)
        if keyword.normalized is None:
            fail("C1-IX-030", "Keyword normalization is unavailable", record.id)
        if version and (
            len(version) != 1
            or not isinstance(version[0], LiteralValue)
            or version[0].lexical != keyword.normalization_version
        ):
            fail("C1-IX-030", "Stored keyword normalization version is unsupported", record.id)
        properties[_C1 + "normalizedKeyword"] = [
            LiteralValue(lexical=keyword.normalized, datatype=_XSD + "string")
        ]
        properties[_C1 + "normalizationVersion"] = [
            LiteralValue(lexical=keyword.normalization_version, datatype=_XSD + "string")
        ]
        if language is not None and keyword.language is not None:
            properties[_C1 + "keywordLanguage"] = [
                LiteralValue(lexical=keyword.language, datatype=_XSD + "string")
            ]
        normalized_node = record.model_copy(update={"properties": properties})
        keyword_nodes[record.id] = normalized_node
        canonical.append(normalized_node)
    # Coalescing applies to an entity's references, not globally: distinct
    # entities may intentionally cite different keyword resources.
    result: list[NodeRecord] = []
    coalesced_links: set[str] = set()
    for record in canonical:
        if _C1 + "Entity" not in record.types:
            result.append(record)
            continue
        links = record.properties.get(_C1 + "keyword", [])
        kept: list[str | LiteralValue] = []
        seen: set[tuple[str | None, str]] = set()
        for link in links:
            if not isinstance(link, str) or link not in keyword_nodes:
                kept.append(link)
                continue
            keyword_node = keyword_nodes[link]
            keyword_language_values = keyword_node.properties.get(_C1 + "keywordLanguage", [])
            normalized_value = keyword_node.properties[_C1 + "normalizedKeyword"][0]
            key = (
                keyword_language_values[0].lexical
                if keyword_language_values and isinstance(keyword_language_values[0], LiteralValue)
                else None,
                normalized_value.lexical if isinstance(normalized_value, LiteralValue) else "",
            )
            if key in seen:
                coalesced_links.add(link)
                diagnostics.append(
                    Diagnostic(
                        code="C1-IX-041",
                        severity="info",
                        path=record.id,
                        message="Coalesced duplicate keyword spelling for this entity",
                    )
                )
            else:
                seen.add(key)
                kept.append(link)
        if len(kept) != len(links):
            properties = dict(record.properties)
            properties[_C1 + "keyword"] = kept
            record = record.model_copy(update={"properties": properties})
        result.append(record)
    referenced_keywords = {
        value
        for record in result
        for values in record.properties.values()
        for value in values
        if isinstance(value, str)
    }
    result = [
        record
        for record in result
        if record.id not in coalesced_links or record.id in referenced_keywords
    ]
    return result, diagnostics


def validate_records(
    records: Iterable[NodeRecord], registry: ProfileRegistry | None = None
) -> ValidatedBatch:
    """Validate caller-constructed records as rigorously as imported JSON-LD."""
    registry = registry or ProfileRegistry()
    normalized, diagnostics = _canonicalize(list(records))
    seen: set[str] = set()
    for record in normalized:
        validate_iri(record.id)
        for class_iri in record.types:
            validate_iri(class_iri)
        for predicate, values in record.properties.items():
            validate_iri(predicate)
            for value in values:
                if isinstance(value, str):
                    validate_iri(value)
        if record.id in seen:
            fail("C1-IX-030", "Duplicate subject in one batch", record.id)
        seen.add(record.id)
        _validate_record(record, registry)
        _semantic_assertion(record, registry)
        _semantic_boundary(record)
    from c1.interchange.shacl import validate_shacl

    validate_shacl(graph_from_records(normalized), registry)
    diagnostics.extend(duplicate_candidates(normalized))
    return ValidatedBatch(records=normalized, diagnostics=diagnostics)


def _semantic_boundary(record: NodeRecord) -> None:
    if _C1 + "TimeBoundary" not in record.types:
        return
    states = record.properties.get(_C1 + "boundaryState", [])
    state = states[0].lexical if len(states) == 1 and isinstance(states[0], LiteralValue) else ""
    time_prefix = "http://www.w3.org/2006/time#"
    time_values = [
        value
        for name in (
            "inXSDDateTimeStamp",
            "inXSDDateTime",
            "inXSDDate",
            "inXSDgYearMonth",
            "inXSDgYear",
        )
        for value in record.properties.get(time_prefix + name, [])
    ]
    if (state == "known" and len(time_values) != 1) or (
        state in {"unknown", "unbounded"} and time_values
    ):
        fail("C1-IX-030", "Boundary state disagrees with precision value", record.id)


def import_jsonld(
    payload: dict[str, Any], registry: ProfileRegistry | None = None
) -> ValidatedBatch:
    """Normalize a supported JSON-LD document; fail atomically on any error."""
    registry = registry or ProfileRegistry()
    if not isinstance(payload, dict):
        fail("C1-IX-030", "JSON-LD input must be an object")
    _reject_keywords(payload)
    context_id = payload.get("@context")
    if not isinstance(context_id, str):
        fail("C1-IX-001", "A bundled @context identifier is required", "@context")
    context = _context_map(registry, context_id)
    if "@graph" in payload:
        if set(payload) != {"@context", "@graph"}:
            fail("C1-IX-030", "Graph document has unexpected keys")
        raw_nodes = payload["@graph"]
        if not isinstance(raw_nodes, list):
            fail("C1-IX-030", "@graph must be an array", "@graph")
    else:
        raw_nodes = [{key: value for key, value in payload.items() if key != "@context"}]
    records = [
        _node(node, context, f"@graph[{index}]", registry) for index, node in enumerate(raw_nodes)
    ]
    batch = validate_records(records, registry)
    _check_rdflib_expansion(payload, records, registry)
    return batch


def _resolve_bundled_contexts(value: Any, registry: ProfileRegistry) -> Any:
    if isinstance(value, list):
        return [_resolve_bundled_contexts(item, registry) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "@context":
                if not isinstance(item, str):
                    fail("C1-IX-001", "Inline or composite contexts are unsupported", key)
                result[key] = _context_map(registry, item)
            else:
                result[key] = _resolve_bundled_contexts(item, registry)
        return result
    return value


def _check_rdflib_expansion(
    payload: dict[str, Any], records: list[NodeRecord], registry: ProfileRegistry
) -> None:
    """Prove the lexical bridge has the semantics of the JSON-LD 1.1 parser."""
    safe = _resolve_bundled_contexts(payload, registry)
    parsed = Graph()
    try:
        parsed.parse(data=json.dumps(safe, ensure_ascii=False), format="json-ld")
    except Exception as exc:
        fail("C1-IX-030", f"JSON-LD expansion failed: {type(exc).__name__}")

    # RDFLib's JSON-LD parser canonicalizes some XSD value spellings, e.g.
    # boolean "1" and integer "+001". Compare normalized *copies* of both
    # graphs while the records retain the submitted lexical strings.
    def comparable(graph: Graph) -> Graph:
        normalized = Graph()
        for subject, predicate, obj in graph:
            if isinstance(obj, Literal):
                datatype = obj.datatype or (XSD.string if obj.language is None else None)
                language = obj.language.lower() if obj.language is not None else None
                obj = Literal(str(obj), datatype=datatype, lang=language, normalize=True)
            normalized.add((subject, predicate, obj))
        return normalized

    if not isomorphic(comparable(parsed), comparable(graph_from_records(records))):
        fail("C1-IX-030", "JSON-LD expansion differs from supported record interpretation")


def graph_from_records(records: Iterable[NodeRecord]) -> Graph:
    """Build RDF terms directly so lexical forms are never normalized by a parser."""
    graph = Graph()
    for record in records:
        subject = URIRef(record.id)
        for class_iri in record.types:
            graph.add((subject, RDF.type, URIRef(class_iri)))
        for predicate, values in record.properties.items():
            for value in values:
                rdf_value = URIRef(value) if isinstance(value, str) else value.to_rdf()
                graph.add((subject, URIRef(predicate), rdf_value))
    return graph


def duplicate_candidates(
    records: Iterable[NodeRecord], visible_existing: Iterable[NodeRecord] = ()
) -> list[Diagnostic]:
    """Suggest similar visible entities without resolving or querying identities.

    The caller supplies only records it is authorized to see.  This function
    has no storage access, so an inaccessible identity cannot affect a result.
    """
    from c1.model.keywords import normalize

    incoming = list(records)
    existing = list(visible_existing)

    def signature(entity: NodeRecord, all_records: list[NodeRecord]) -> tuple[object, ...]:
        lookup = {record.id: record for record in all_records}
        labels = tuple(
            sorted(
                (
                    (value.language, normalize(value.lexical))
                    for value in entity.properties.get(_SKOS_LABEL, [])
                    if isinstance(value, LiteralValue)
                ),
                key=lambda item: (item[0] or "", item[1]),
            )
        )
        keywords: list[tuple[str | None, str]] = []
        for link in entity.properties.get(_C1 + "keyword", []):
            if not isinstance(link, str) or link not in lookup:
                continue
            node = lookup[link]
            text = node.properties.get(_C1 + "keywordText", [])
            language = node.properties.get(_C1 + "keywordLanguage", [])
            if len(text) != 1 or not isinstance(text[0], LiteralValue):
                continue
            keywords.append(
                (
                    language[0].lexical.lower()
                    if language and isinstance(language[0], LiteralValue)
                    else None,
                    normalize(text[0].lexical),
                )
            )
        return labels, tuple(sorted(keywords, key=lambda item: (item[0] or "", item[1])))

    old_entities = [record for record in existing if _C1 + "Entity" in record.types]
    incoming_entities = [record for record in incoming if _C1 + "Entity" in record.types]
    diagnostics: list[Diagnostic] = []
    for index, entity in enumerate(incoming_entities):
        own = signature(entity, incoming)
        candidates = [(item, existing) for item in old_entities]
        candidates.extend((item, incoming) for item in incoming_entities[:index])
        for previous, pool in candidates:
            if previous.id != entity.id and signature(previous, pool) == own:
                diagnostics.append(
                    Diagnostic(
                        code="C1-IX-040",
                        severity="info",
                        path=entity.id,
                        message=f"DuplicateCandidate: visible entity {previous.id}",
                    )
                )
    return diagnostics
