"""Pure structured presentation of the caller's authorized evidence units."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from c1.changes.digest import canonical_json


def public_value(value: Any) -> Any:
    """Copy a JSON projection while removing internal dependency/checkpoint keys."""
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [public_value(item) for item in value]
    return deepcopy(value)


def unit_citations(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a unit's own citations, then claim and qualifier citations in first-use order."""
    result: list[dict[str, Any]] = list(unit.get("citations", []))

    def visit(claim: dict[str, Any]) -> None:
        result.extend(claim.get("citations", []))
        for qualifier in claim.get("qualifiers", []):
            visit(qualifier)

    for claim in unit.get("claims", []):
        visit(claim)
    return result


def parity_identifiers(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Include citation-free units and exact citation identities in the parity proof."""
    return [
        {
            "unit_id": unit["id"],
            "citations": [
                {"id": citation["id"], "n": citation["n"]} for citation in unit_citations(unit)
            ],
        }
        for unit in units
    ]


def _returned_graph(
    base: dict[str, Any], units: list[dict[str, Any]]
) -> tuple[set[str], dict[str, set[str]], dict[tuple[str, str, str], set[str]]]:
    """Index only relationship endpoints and edges appearing in this package."""
    types: dict[str, set[str]] = {}
    starts: set[str] = set()
    edges: list[tuple[str, str, str]] = []

    def node(identifier: str, declared: list[str]) -> None:
        types.setdefault(identifier, set()).update(declared)

    anchor = base.get("interpretation", {}).get("anchor", {})
    if anchor.get("id"):
        starts.add(anchor["id"])
        node(anchor["id"], anchor.get("types", []))
    for path in base.get("orientation", []):
        for item in path.get("nodes", []):
            node(item["id"], item.get("types", []))
        for edge in path.get("edges", []):
            if all(edge.get(key) for key in ("subject", "predicate", "object")):
                edges.append((edge["subject"], edge["predicate"], edge["object"]))
    for unit in units:
        starts.add(unit["node_id"])
        node(unit["node_id"], unit.get("node_types", []))
        for claim in unit.get("claims", []):
            value = claim["value"]
            if value.get("kind") == "iri":
                node(value["id"], value.get("types", []))
                edges.append((unit["node_id"], unit["predicate"], value["id"]))
    adjacency: dict[tuple[str, str, str], set[str]] = {}
    for subject, predicate, target in edges:
        if subject in types and target in types:
            adjacency.setdefault((subject, predicate, "out"), set()).add(target)
            adjacency.setdefault((target, predicate, "in"), set()).add(subject)
    return starts, types, adjacency


def _path_present(
    path: dict[str, Any],
    starts: set[str],
    types: dict[str, set[str]],
    adjacency: dict[tuple[str, str, str], set[str]],
) -> bool:
    steps = path.get("steps", [])
    if not steps or len(steps) > min(3, path.get("max_depth", 0)):
        return False
    frontier = starts
    for step in steps:
        targets: set[str] = set()
        required_types = set(step.get("target_types", []))
        for identifier in frontier:
            for target in adjacency.get((identifier, step["predicate"], step["direction"]), ()):
                if not required_types or required_types.intersection(types[target]):
                    targets.add(target)
        frontier = targets
        if not frontier:
            return False
    return True


def render_structured(
    base: dict[str, Any], units: list[dict[str, Any]], bounds: dict[str, Any]
) -> dict[str, Any]:
    """Preserve values, qualifications, and excerpts without inference or reads."""
    selected = public_value(units)
    citations: dict[int, dict[str, Any]] = {}
    text = []
    for unit in selected:
        seen: set[int] = set()
        for citation in unit_citations(unit):
            citations.setdefault(citation["n"], citation)
            if "excerpt" in citation and citation["n"] not in seen:
                text.append({"unit_id": unit["id"], **citation})
                seen.add(citation["n"])
    predicates = {unit["predicate"] for unit in selected}
    mappings = base.get("field_predicates", {})
    graph = _returned_graph(base, selected)
    gaps = []
    for field in base.get("fields", []):
        mapping = mappings.get(field)
        present = (
            mapping in predicates
            if isinstance(mapping, str)
            else _path_present(mapping, *graph)
            if isinstance(mapping, dict)
            else False
        )
        if not present:
            gaps.append({"field": field, "message": "not present in the returned material"})
    identifiers = parity_identifiers(selected)
    return {
        "title": "Context: " + base.get("anchor_label", ""),
        "interpretation": public_value(base.get("interpretation", {})),
        "orientation": public_value(base.get("orientation", [])),
        "facts": selected,
        "text": text,
        "disagreements": [
            {"unit_id": unit["id"], **unit["disagreement"]}
            for unit in selected
            if unit.get("disagreement", {}).get("competing")
        ],
        "gaps": gaps,
        "sources": [citations[n] for n in sorted(citations)],
        "bounds": public_value(bounds),
        "format_parity_digest": hashlib.sha256(
            canonical_json(identifiers).encode("utf-8")
        ).hexdigest(),
    }
