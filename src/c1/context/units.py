"""Indivisible evidence units from an already authorized selection.

This module performs no reads and grants no authority. Every content join is
restricted to the request's AuthorizedRecords; missing dependencies simply
remove their projection, never reveal a protected-resource placeholder.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from typing import Any

from c1.changes.validation import _known_overlap, _single_valued_for_subject
from c1.context.errors import ContextError
from c1.context.profiles import ContextProfile
from c1.documents.validation import selector_diagnostics
from c1.model.keywords import normalize
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, DCTERMS, OA, PROV, RDF, SKOS
from c1.model.time import TimeBoundary, TimeInterval
from c1.query.service import TIME, AuthorizedRecords, _intervals, _iri, _text

MAX_UNITS = 500
MAX_EXCERPT_BYTES = 4096
_REVIEW_ORDER = {"confirmed": 0, "reported": 1, "disputed": 2}


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ContextError(503, "C1-QY-053", "time_budget")


def _identifier(kind: str, *parts: str) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"urn:c1:context:{kind}:" + hashlib.sha256(encoded).hexdigest()


def _label(node: NodeRecord) -> str:
    labels = [
        item
        for item in node.properties.get(SKOS + "prefLabel", ())
        if isinstance(item, LiteralValue)
    ]
    if labels:
        return min(
            labels, key=lambda item: (normalize(item.lexical), item.language or "", item.lexical)
        ).lexical
    return _text(node, DCTERMS + "title") or node.id


def _predicate_label(predicate: str, registry: ProfileRegistry) -> str:
    definition = registry.predicates.get(predicate)
    return definition.name if definition is not None else predicate


def _declared_predicates(node: NodeRecord, registry: ProfileRegistry) -> set[str]:
    definition = registry.primary_class(node.types)
    predicates = set(definition.properties)
    for profile in registry.profiles.values():
        if definition.iri in profile.classes:
            predicates.update(profile.predicates)
    return predicates


def _roles(
    records: AuthorizedRecords, matched: dict[str, Any], profile: ContextProfile
) -> dict[str, list[dict[str, Any]]]:
    """Classify explicit path nodes by declared types in anchor-to-target order."""
    current = matched["node_id"]
    reverse_nodes = [current]
    for assertion_id in reversed(matched.get("path", [])):
        edge = records.get(assertion_id)
        if edge is None or C1 + "Assertion" not in edge.types:
            reverse_nodes = [matched["node_id"]]
            break
        subject, obj = _iri(edge, RDF + "subject"), _iri(edge, RDF + "object")
        predecessor = obj if subject == current else subject if obj == current else None
        if predecessor is None or predecessor not in records:
            reverse_nodes = [matched["node_id"]]
            break
        reverse_nodes.append(predecessor)
        current = predecessor
    path_nodes = [records[identifier] for identifier in dict.fromkeys(reversed(reverse_nodes))]
    return {
        role: [
            {"id": node.id, "label": _label(node), "types": sorted(node.types)}
            for node in path_nodes
            if set(node.types).intersection(types)
        ]
        for role, types in sorted(profile.role_types.items())
    }


def _value(value: str | LiteralValue, records: AuthorizedRecords) -> dict[str, Any] | None:
    if isinstance(value, LiteralValue):
        return {"kind": "literal", **value.model_dump(mode="json", exclude_none=True)}
    target = records.get(value)
    if target is None:
        return None
    return {"kind": "iri", "id": target.id, "label": _label(target), "types": sorted(target.types)}


def _boundary_projection(boundary: TimeBoundary) -> dict[str, Any]:
    result = boundary.model_dump(mode="json", exclude_none=True)
    if boundary.datatype is not None:
        result["precision"] = boundary.datatype.rsplit("#", 1)[-1]
        result["timezone_unknown"] = boundary.timezone_unknown
    return result


def _metadata(
    assertion: NodeRecord,
    records: AuthorizedRecords,
    intervals: dict[str, TimeInterval],
    dependencies: set[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "assertion_id": assertion.id,
        "review_state": _text(assertion, C1 + "reviewState") or "reported",
        "origin": _text(assertion, C1 + "origin"),
        "lifecycle": _text(assertion, C1 + "lifecycle") or "active",
    }
    dependencies.add(assertion.id)
    interval_id = _iri(assertion, C1 + "validDuring")
    interval = intervals.get(interval_id) if interval_id else None
    unknown = TimeBoundary(state="unknown")
    result["valid_time"] = {
        "start": _boundary_projection(interval.start if interval else unknown),
        "end": _boundary_projection(interval.end if interval else unknown),
    }
    if interval_id is not None and interval_id in records:
        dependencies.add(interval_id)
        result["valid_time"]["interval_id"] = interval_id
        for predicate in (TIME + "hasBeginning", TIME + "hasEnd"):
            boundary_id = _iri(records[interval_id], predicate)
            if boundary_id is not None and boundary_id in records:
                dependencies.add(boundary_id)
    for predicate, key in ((C1 + "confidence", "confidence"),):
        literal = next(
            (
                item
                for item in assertion.properties.get(predicate, ())
                if isinstance(item, LiteralValue)
            ),
            None,
        )
        if literal is not None:
            result[key] = literal.model_dump(mode="json", exclude_none=True)
    method = _text(assertion, C1 + "confidenceMethod")
    if method is not None:
        result["confidence_method"] = method
    actor = _iri(assertion, PROV + "wasAttributedTo")
    if actor is not None:
        # Principal/organizational IRIs are attribution, not content joins.
        result["attributed_to"] = actor
        if actor in records:
            dependencies.add(actor)
    activity_id = _iri(assertion, PROV + "wasGeneratedBy")
    if (
        activity_id is not None
        and activity_id in records
        and PROV + "Activity" in records[activity_id].types
    ):
        result["activity"] = _activity(records[activity_id], dependencies, records)
    if result["origin"] == "derived":
        result["attribution_kind"] = "externally_authored_derivation"
    if _text(assertion, C1 + "manualStatement") in {"true", "1"} and actor is not None:
        result["manual_statement"] = True
    return result


def _activity(
    node: NodeRecord, dependencies: set[str], records: AuthorizedRecords
) -> dict[str, Any]:
    dependencies.add(node.id)
    result: dict[str, Any] = {"id": node.id}
    actor = _iri(node, PROV + "wasAttributedTo")
    if actor is not None:
        result["actor"] = actor
        if actor in records:
            dependencies.add(actor)
    for predicate, key in (
        (C1 + "method", "method"),
        (C1 + "toolName", "tool_name"),
        (C1 + "toolVersion", "tool_version"),
    ):
        value = _text(node, predicate)
        if value is not None:
            result[key] = value
    return result


def _selector(node: NodeRecord) -> dict[str, Any]:
    """Project only the selector vocabulary, never arbitrary stored fields."""
    result: dict[str, Any] = {"id": node.id, "kind": _text(node, C1 + "selectorKind")}
    for predicate, key in (
        (OA + "exact", "exact"),
        (OA + "prefix", "prefix"),
        (OA + "suffix", "suffix"),
        (OA + "start", "start"),
        (OA + "end", "end"),
    ):
        value = _text(node, predicate)
        if value is not None:
            result[key] = value
    return result


def _excerpt(text: str) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    return encoded[:MAX_EXCERPT_BYTES].decode("utf-8", errors="ignore"), (
        len(encoded) > MAX_EXCERPT_BYTES
    )


class _Projection:
    def __init__(
        self,
        records: AuthorizedRecords,
        profile: ContextProfile,
        registry: ProfileRegistry,
        deadline: float,
    ) -> None:
        self.records, self.profile, self.registry, self.deadline = (
            records,
            profile,
            registry,
            deadline,
        )
        self.intervals = _intervals(records)
        self.assertions: dict[tuple[str, str], list[NodeRecord]] = defaultdict(list)
        self.evidence: dict[str, list[NodeRecord]] = defaultdict(list)
        for node in records.values():
            _check_deadline(deadline)
            if C1 + "Assertion" in node.types and _text(node, C1 + "lifecycle") == "active":
                subject, predicate = _iri(node, RDF + "subject"), _iri(node, RDF + "predicate")
                if subject is not None and subject in records and predicate:
                    self.assertions[(subject, predicate)].append(node)
            if C1 + "Evidence" in node.types:
                assertion_id = _iri(node, C1 + "assertionRef")
                if assertion_id is not None and assertion_id in records:
                    self.evidence[assertion_id].append(node)

    def citations(self, claim: NodeRecord, dependencies: set[str]) -> list[dict[str, Any]]:
        candidates = {item.id: item for item in self.evidence.get(claim.id, ())}
        for value in claim.properties.get(C1 + "evidence", ()):
            if isinstance(value, str) and value in self.records:
                evidence = self.records[value]
                if (
                    C1 + "Evidence" in evidence.types
                    and _iri(evidence, C1 + "assertionRef") == claim.id
                ):
                    candidates[value] = evidence
        result = []
        for evidence in sorted(candidates.values(), key=lambda item: item.id):
            _check_deadline(self.deadline)
            citation = self.citation(evidence, dependencies)
            if citation is not None:
                result.append(citation)
        return result

    def citation(self, evidence: NodeRecord, dependencies: set[str]) -> dict[str, Any] | None:
        target_id = _iri(evidence, OA + "hasSource")
        target = self.records.get(target_id) if target_id else None
        if target is None:
            return None
        local_dependencies = {evidence.id, target.id}
        source, part, document = target, None, None
        source_link = None
        if C1 + "DocumentPart" in target.types:
            part = target
            document_id = _iri(part, C1 + "partOfDocument")
            document = self.records.get(document_id) if document_id else None
            if document is None or C1 + "Document" not in document.types:
                return None
            document_revision = _text(document, C1 + "sourceRevision")
            if (
                document_revision is None
                or _text(evidence, C1 + "sourceRevision") != document_revision
            ):
                # A selector cannot turn old evidence into a citation of an
                # edited document, even if its offsets are still in bounds.
                return None
            links = self.assertions.get((document.id, self.profile.document_source_predicate), [])
            sources = [
                (link, item)
                for link in links
                if (item := self.records.get(_iri(link, RDF + "object") or "")) is not None
                and C1 + "Source" in item.types
            ]
            if len(sources) != 1:
                return None
            source_link, source = sources[0]
            assert source is not None
            local_dependencies.update((document.id, source.id, source_link.id))
        if C1 + "Source" not in source.types:
            return None
        result: dict[str, Any] = {
            "id": _identifier("citation", evidence.id),
            "evidence_id": evidence.id,
            "evidence_target_id": target.id,
            "evidence_source_revision": _text(evidence, C1 + "sourceRevision"),
            "source_id": source.id,
            "source_title": _text(source, DCTERMS + "title") or source.id,
            "source_kind": _text(source, C1 + "sourceKind"),
            "source_revision": _text(source, C1 + "sourceRevision"),
            "imported_by": [],
            "import_activities": [],
            "corroboration": "distinct_sources",
        }
        if part is not None and document is not None and source_link is not None:
            result.update(
                part_id=part.id, document_id=document.id, source_link_assertion_id=source_link.id
            )
        selector_id = _iri(evidence, OA + "hasSelector")
        selector = self.records.get(selector_id) if selector_id else None
        selected_text = None
        if selector is not None and C1 + "Selector" in selector.types:
            # Part selectors must refer to the exact authorized part text.
            if part is None or not selector_diagnostics(selector, part, "selector"):
                result["selector"] = _selector(selector)
                local_dependencies.add(selector.id)
                if part is not None:
                    kind = _text(selector, C1 + "selectorKind")
                    if kind == "TextQuoteSelector":
                        selected_text = _text(selector, OA + "exact")
                    elif kind == "TextPositionSelector":
                        body = _text(part, C1 + "text") or ""
                        selected_text = body[
                            int(_text(selector, OA + "start") or "0") : int(
                                _text(selector, OA + "end") or "0"
                            )
                        ]
        text = _text(evidence, C1 + "excerpt")
        if text is None:
            text = selected_text
        if text is not None:
            result["excerpt"], result["excerpt_truncated"] = _excerpt(text)
            kind = _text(part, C1 + "partKind") if part is not None else None
            result["excerpt_kind"] = "code" if kind and kind.startswith("code") else "text"
        activity_id = _iri(evidence, PROV + "wasGeneratedBy")
        activity = self.records.get(activity_id) if activity_id else None
        if activity is not None and PROV + "Activity" in activity.types:
            used = activity.properties.get(PROV + "used", [])
            outputs = activity.properties.get(C1 + "output", [])
            if (not used or source.id in used or target.id in used) and (
                not outputs or evidence.id in outputs
            ):
                result["imported_by"] = [activity.id]
                result["import_activities"] = [
                    _activity(activity, local_dependencies, self.records)
                ]
                local_dependencies.update(
                    item
                    for item in (*used, *outputs)
                    if isinstance(item, str) and item in self.records
                )
        dependencies.update(local_dependencies)
        return result

    def claim(self, assertion: NodeRecord, dependencies: set[str]) -> dict[str, Any] | None:
        objects = assertion.properties.get(RDF + "object", ())
        if len(objects) != 1 or (value := _value(objects[0], self.records)) is None:
            return None
        if isinstance(objects[0], str):
            dependencies.add(objects[0])
        result = _metadata(assertion, self.records, self.intervals, dependencies)
        result.update(
            value=value,
            citations=self.citations(assertion, dependencies),
            qualifiers=[],
            incomplete=[],
        )
        return result

    def measurement(
        self, assertion: NodeRecord, claim: dict[str, Any], dependencies: set[str]
    ) -> None:
        predicate = _iri(assertion, RDF + "predicate") or ""
        required = self.profile.required_qualifiers.get(predicate, [])
        links = self.assertions.get((assertion.id, self.profile.measurement_predicate or ""), [])
        definition = self.registry.predicates.get(self.profile.measurement_predicate or "")
        measurement_types = (
            {kind for kind in definition.ranges if kind in self.registry.classes}
            if definition is not None
            else set()
        )
        associations = [
            (link, node)
            for link in links
            if (node := self.records.get(_iri(link, RDF + "object") or "")) is not None
            and measurement_types.intersection(node.types)
        ]
        if len(associations) > 1:
            claim["measurement_status"] = "ambiguous"
            claim["measurement_links"] = [
                {"assertion_id": link.id, "measurement_id": node.id}
                for link, node in sorted(associations, key=lambda item: item[0].id)
            ]
            dependencies.update(item.id for pair in associations for item in pair)
        elif len(associations) == 1:
            link, node = associations[0]
            claim.update(measurement_id=node.id, measurement_link_assertion_id=link.id)
            claim["measurement_link"] = _metadata(link, self.records, self.intervals, dependencies)
            dependencies.add(node.id)
            for qualifier_predicate in self.profile.qualifier_predicates:
                for qualifier in self.assertions.get((node.id, qualifier_predicate), ()):
                    projected = self.claim(qualifier, dependencies)
                    if projected is not None:
                        projected.update(
                            predicate=qualifier_predicate,
                            predicate_label=_predicate_label(qualifier_predicate, self.registry),
                        )
                        claim["qualifiers"].append(projected)
            claim["qualifiers"].sort(key=lambda item: (item["predicate"], item["assertion_id"]))
        present = {item["predicate"] for item in claim["qualifiers"]}
        claim["incomplete"] = [
            _predicate_label(item, self.registry) for item in required if item not in present
        ]

    def comparison(
        self,
        subject: NodeRecord,
        predicate: str,
        assertions: dict[str, NodeRecord],
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        differing = [
            (left, right)
            for index, left in enumerate(claims)
            for right in claims[index + 1 :]
            if left["value"] != right["value"]
        ]
        single = _single_valued_for_subject(self.registry, subject, predicate)
        conflicts = []
        required = self.profile.required_qualifiers.get(predicate, [])
        for left, right in differing:
            _check_deadline(self.deadline)
            comparable = not left["incomplete"] and not right["incomplete"]
            for qualifier_predicate in required:
                a = [
                    item["value"]
                    for item in left["qualifiers"]
                    if item["predicate"] == qualifier_predicate
                ]
                b = [
                    item["value"]
                    for item in right["qualifiers"]
                    if item["predicate"] == qualifier_predicate
                ]
                comparable &= len(a) == 1 and len(b) == 1 and a == b
            a_interval = _iri(assertions[left["assertion_id"]], C1 + "validDuring")
            b_interval = _iri(assertions[right["assertion_id"]], C1 + "validDuring")
            if (
                single
                and comparable
                and _known_overlap(
                    self.intervals.get(a_interval or ""), self.intervals.get(b_interval or "")
                )
            ):
                conflicts.append([left["assertion_id"], right["assertion_id"]])
        comparison = (
            "agreement"
            if not differing
            else "multiple_values"
            if not single
            else "disagreement"
            if conflicts
            else "unresolved"
        )
        result: dict[str, Any] = {"comparison": comparison}
        if differing:
            result["disagreement"] = {
                "competing": single,
                "declared_conflict": bool(conflicts),
                "pairs": conflicts,
                "competing_assertion_ids": sorted(
                    {claim["assertion_id"] for pair in differing for claim in pair}
                ),
            }
            if conflicts:
                result["disagreement"]["basis"] = "declared_single_value_known_overlap"
        return result


def build_units(
    records: AuthorizedRecords,
    selection: dict[str, Any],
    profile: ContextProfile,
    registry: ProfileRegistry,
    *,
    deadline: float,
) -> list[dict[str, Any]]:
    """Group all readable active claims without splitting their qualifications."""
    _check_deadline(deadline)
    projection = _Projection(records, profile, registry, deadline)
    units: list[dict[str, Any]] = []
    for matched in selection.get("matched", []):
        node_id = matched["node_id"]
        node = records.get(node_id)
        if node is None:
            continue
        allowed = (
            _declared_predicates(node, registry)
            if profile.fact_predicates == "declared"
            else set(profile.fact_predicates)
        )
        roles = _roles(records, matched, profile)
        path_dependencies = {node.id} | {
            identifier for identifier in matched.get("_dependencies", []) if identifier in records
        }
        for assertion_id in matched.get("path", []):
            edge = records.get(assertion_id)
            if edge is not None:
                path_dependencies.add(edge.id)
                for predicate in (RDF + "subject", RDF + "object"):
                    target = _iri(edge, predicate)
                    if target is not None and target in records:
                        path_dependencies.add(target)
        for predicate in sorted(allowed):
            assertions = projection.assertions.get((node.id, predicate), [])
            if not assertions:
                continue
            dependencies = set(path_dependencies)
            claims = []
            for assertion in assertions:
                _check_deadline(deadline)
                claim = projection.claim(assertion, dependencies)
                if claim is not None:
                    projection.measurement(assertion, claim, dependencies)
                    claims.append(claim)
            if not claims:
                continue
            claims.sort(
                key=lambda claim: (
                    _REVIEW_ORDER.get(claim["review_state"], 3),
                    min(
                        (normalize(item["source_title"]) for item in claim["citations"]), default=""
                    ),
                    claim["assertion_id"],
                )
            )
            citations = [citation for claim in claims for citation in claim["citations"]]
            citations.extend(
                citation
                for claim in claims
                for qualifier in claim["qualifiers"]
                for citation in qualifier["citations"]
            )
            source_versions: dict[str, set[str]] = defaultdict(set)
            imports_by_source: dict[str, set[str]] = defaultdict(set)
            for citation in citations:
                source_versions[citation["source_id"]]
                version_keys = (
                    ("source_revision",)
                    if "part_id" in citation
                    else ("source_revision", "evidence_source_revision")
                )
                for key in version_keys:
                    if citation[key] is not None:
                        source_versions[citation["source_id"]].add(citation[key])
                imports_by_source[citation["source_id"]].update(citation["imported_by"])
            for citation in citations:
                if len(imports_by_source[citation["source_id"]]) > 1:
                    citation["corroboration"] = "duplicate_import"
            unit = {
                "id": _identifier("unit", node.id, predicate),
                "node_id": node.id,
                "node_label": _label(node),
                "node_types": sorted(node.types),
                "roles": roles,
                "distance": matched["distance"],
                "predicate": predicate,
                "predicate_label": _predicate_label(predicate, registry),
                "claims": claims,
                "sources": len(source_versions),
                "source_versions": [
                    {"source_id": source_id, "revisions": sorted(revisions)}
                    for source_id, revisions in sorted(source_versions.items())
                ],
                "imports": len(
                    {activity for imports in imports_by_source.values() for activity in imports}
                ),
                **projection.comparison(
                    node, predicate, {item.id: item for item in assertions}, claims
                ),
                "_dependencies": sorted(dependencies),
            }
            units.append(unit)
            if len(units) > MAX_UNITS:
                raise ContextError(422, "C1-CX-012", "too_many_units; narrow topics")
    units.sort(
        key=lambda unit: (
            unit["distance"],
            normalize(unit["node_label"]),
            unit["node_id"],
            unit["predicate"],
        )
    )
    _check_deadline(deadline)
    return units
