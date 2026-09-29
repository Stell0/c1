"""Exact selector resolution over records already authorized by M05."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from c1.context.errors import ContextError
from c1.context.profiles import ContextProfile
from c1.context.request import IDSelector, LabelSelector
from c1.model.keywords import normalize
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, SKOS

IDENTITY = "urn:c1:ns:identity#"


def single_iri(node: NodeRecord, predicate: str) -> str | None:
    values = node.properties.get(predicate, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def lifecycle(node: NodeRecord) -> str | None:
    values = node.properties.get(C1 + "lifecycle", [])
    return values[0].lexical if len(values) == 1 and isinstance(values[0], LiteralValue) else None


def primary_label(node: NodeRecord) -> str:
    labels = [
        value
        for value in node.properties.get(SKOS + "prefLabel", [])
        if isinstance(value, LiteralValue)
    ]
    labels.sort(key=lambda value: (normalize(value.lexical), value.language or "", value.lexical))
    return labels[0].lexical if labels else node.id


def candidate(node: NodeRecord) -> dict[str, Any]:
    return {"id": node.id, "label": primary_label(node), "types": sorted(node.types)}


def label_matches(node: NodeRecord, selector: LabelSelector) -> bool:
    return any(
        isinstance(value, LiteralValue)
        and normalize(value.lexical) == normalize(selector.label)
        and (selector.language is None or value.language == selector.language)
        for predicate in (SKOS + "prefLabel", SKOS + "altLabel")
        for value in node.properties.get(predicate, [])
    )


def anchor_allowed(
    node: NodeRecord, profile: ContextProfile, registry: ProfileRegistry | None = None
) -> bool:
    allowed = set(profile.anchor_types)
    entity = (
        registry.is_entity(node.types)
        if registry is not None
        else (C1 + "Entity" in node.types or bool(allowed.intersection(node.types)))
    )
    return entity and (C1 + "Entity" in allowed or bool(allowed.intersection(node.types)))


def _survivor(
    records: Mapping[str, NodeRecord],
    node: NodeRecord,
    profile: ContextProfile,
    registry: ProfileRegistry | None,
    dependencies: set[str],
) -> NodeRecord | None:
    seen: set[str] = set()
    dependencies.add(node.id)
    while lifecycle(node) == "superseded":
        if node.id in seen:
            return None
        seen.add(node.id)
        redirects = [
            item
            for item in records.values()
            if IDENTITY + "Redirect" in item.types
            and lifecycle(item) == "active"
            and single_iri(item, IDENTITY + "from") == node.id
            and single_iri(item, IDENTITY + "to") in records
            and single_iri(item, IDENTITY + "resolution") in records
        ]
        if len(redirects) != 1:
            return None
        dependencies.add(redirects[0].id)
        resolution = single_iri(redirects[0], IDENTITY + "resolution")
        assert resolution is not None
        dependencies.add(resolution)
        target = single_iri(redirects[0], IDENTITY + "to")
        assert target is not None
        node = records[target]
        dependencies.add(node.id)
        if not anchor_allowed(node, profile, registry):
            return None
    return node if lifecycle(node) != "retracted" else None


def resolve_anchor(
    records: Mapping[str, NodeRecord],
    selector: IDSelector | LabelSelector,
    profile: ContextProfile,
    registry: ProfileRegistry | None = None,
) -> dict[str, Any]:
    """Unknown and unreadable IDs have exactly the same failure response."""
    eligible = {
        key: node for key, node in records.items() if anchor_allowed(node, profile, registry)
    }
    dependencies: set[str] = set()
    if isinstance(selector, IDSelector):
        node = eligible.get(selector.id)
        resolved = (
            _survivor(records, node, profile, registry, dependencies) if node is not None else None
        )
        if resolved is None:
            raise ContextError(404, "C1-CX-404", "not_found")
        return {
            "outcome": "resolved",
            "anchor": candidate(resolved),
            "_dependencies": sorted(dependencies),
        }
    matches: dict[str, NodeRecord] = {}
    for node in eligible.values():
        if label_matches(node, selector):
            local_dependencies: set[str] = set()
            survivor = _survivor(records, node, profile, registry, local_dependencies)
            if survivor is not None:
                matches[survivor.id] = survivor
                dependencies.update(local_dependencies)
    candidates = [candidate(node) for _, node in sorted(matches.items())]
    if len(candidates) == 1:
        return {
            "outcome": "resolved",
            "anchor": candidates[0],
            "_dependencies": sorted(dependencies),
        }
    return {
        "outcome": "ambiguous" if candidates else "unresolved",
        "candidates": candidates,
        "_dependencies": sorted(dependencies),
    }
