"""Ordered typed path selection over an already authorized record set."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from c1.context.errors import ContextError
from c1.context.profiles import ContextProfile
from c1.context.request import ContextRequest
from c1.context.resolve import anchor_allowed, lifecycle, primary_label, single_iri
from c1.context.topics import topic_records
from c1.model.keywords import normalize
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, RDF, SKOS
from c1.query.filters import QueryFilters, evaluate_entity
from c1.query.traverse import traverse_authorized

NODE_LIMIT = 500
EDGE_LIMIT = 2000
DEPTH_LIMIT = 3


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ContextError(503, "C1-CX-014", "time_budget")


def _check_bounds(nodes: set[str], edges: set[str]) -> None:
    if len(nodes) > NODE_LIMIT or len(edges) > EDGE_LIMIT:
        raise ContextError(422, "C1-CX-013", "traversal_bounds")


def _expand_topics(
    records: Mapping[str, NodeRecord],
    topic_ids: set[str],
    profile: ContextProfile,
    deadline: float,
    seen_nodes: set[str],
    seen_edges: set[str],
) -> dict[str, set[str]]:
    concepts = topic_records(records, profile)
    topic_ids = set(topic_ids) & concepts.keys()
    if profile.topic_expand == "off":
        return {identifier: {identifier} for identifier in topic_ids}
    # Concepts carry labels and scheme membership. Broader relationships are
    # independently protected claims, just like every traversed domain edge.
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for assertion in records.values():
        _check_deadline(deadline)
        if (
            C1 + "Assertion" not in assertion.types
            or lifecycle(assertion) != "active"
            or single_iri(assertion, RDF + "predicate") != SKOS + "broader"
        ):
            continue
        child = single_iri(assertion, RDF + "subject")
        parent = single_iri(assertion, RDF + "object")
        if child in concepts and parent in concepts:
            assert child is not None and parent is not None
            adjacency.setdefault(parent, []).append((assertion.id, child))
    result: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
        identifier: ((), (identifier,)) for identifier in topic_ids
    }
    frontier = dict(result)
    seen_nodes.update(frontier)
    _check_bounds(seen_nodes, seen_edges)
    for _ in range(DEPTH_LIMIT):
        following: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        for parent, (path, node_path) in sorted(frontier.items()):
            _check_deadline(deadline)
            for assertion_id, child in sorted(adjacency.get(parent, [])):
                seen_nodes.add(child)
                seen_edges.add(assertion_id)
                _check_bounds(seen_nodes, seen_edges)
                candidate_path = ((*path, assertion_id), (*node_path, child))
                if child in result:
                    continue
                previous = following.get(child)
                if previous is None or candidate_path < previous:
                    following[child] = candidate_path
        result.update(following)
        frontier = following
        if not frontier:
            break
    # Refuse an incomplete expansion rather than silently ignoring a descendant.
    if any(child not in result for parent in frontier for _, child in adjacency.get(parent, [])):
        raise ContextError(422, "C1-CX-013", "traversal_bounds")
    return {identifier: {*path, *node_path} for identifier, (path, node_path) in result.items()}


def select_context(
    records: Mapping[str, NodeRecord],
    anchor_id: str,
    topics: Sequence[dict[str, Any] | str],
    profile: ContextProfile,
    request: ContextRequest,
    *,
    deadline: float,
    registry: ProfileRegistry | None = None,
) -> dict[str, Any]:
    """Select matches and their shortest explanatory paths without content fetches.

    Every prefix is eligible to match. Each declared path is evaluated separately,
    so reaching a node through one path cannot unlock a later step in another.
    Bounds cover the union of traversed resources across all paths and optional
    topic expansion. Exceeding a bound returns no partial selection.
    """
    deadline = min(deadline, time.monotonic() + 2)
    _check_deadline(deadline)
    anchor = records.get(anchor_id)
    if anchor is None or not anchor_allowed(anchor, profile, registry):
        raise ContextError(404, "C1-CX-404", "not_found")
    seen_nodes = {anchor_id}
    seen_edges: set[str] = set()
    topic_ids = {item if isinstance(item, str) else item["id"] for item in topics}
    topic_dependencies = _expand_topics(
        records, topic_ids, profile, deadline, seen_nodes, seen_edges
    )
    dependencies = {anchor_id, *(topic_ids & topic_dependencies.keys())}
    if topics and profile.topic_scheme in records:
        dependencies.add(profile.topic_scheme)
    topic_ids = set(topic_dependencies)
    # node ID -> (assertion path, node path), including the depth-zero anchor.
    reached: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {anchor_id: ((), (anchor_id,))}
    for declared in profile.paths:
        frontier: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
            anchor_id: ((), (anchor_id,))
        }
        for step in declared.steps:
            _check_deadline(deadline)
            # Type restrictions are selection semantics, not a cosmetic filter
            # after a broad traversal consumes its hard budgets.
            step_records: list[NodeRecord] = []
            for node in records.values():
                _check_deadline(deadline)
                if C1 + "Assertion" not in node.types:
                    step_records.append(node)
                    continue
                if single_iri(node, RDF + "predicate") != step.predicate:
                    continue
                target_id = single_iri(
                    node, RDF + ("object" if step.direction == "out" else "subject")
                )
                target = records.get(target_id) if target_id is not None else None
                if target is not None and (
                    not step.target_types or set(step.target_types).intersection(target.types)
                ):
                    step_records.append(node)
            following: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
            for node_id, (path, node_path) in sorted(frontier.items()):
                try:
                    traversal = traverse_authorized(
                        step_records,
                        node_id,
                        predicates=frozenset({step.predicate}),
                        direction=step.direction,
                        depth=1,
                        deadline=deadline,
                    )
                except TimeoutError as exc:
                    raise ContextError(503, "C1-CX-014", "time_budget") from exc
                if traversal.truncated:
                    raise ContextError(422, "C1-CX-013", "traversal_bounds")
                for edge in traversal.edges:
                    target_id = edge.object if step.direction == "out" else edge.subject
                    target = records[target_id]
                    if step.target_types and not set(step.target_types).intersection(target.types):
                        continue
                    seen_nodes.add(target_id)
                    seen_edges.add(edge.assertion_id)
                    _check_bounds(seen_nodes, seen_edges)
                    next_path = (*path, edge.assertion_id)
                    item = (next_path, (*node_path, target_id))
                    previous = following.get(target_id)
                    if previous is None or item < previous:
                        following[target_id] = item
                    previous = reached.get(target_id)
                    if previous is None or (len(next_path), item) < (len(previous[0]), previous):
                        reached[target_id] = item
            frontier = following
            if not frontier:
                break
    carrier_dependencies: dict[str, set[str]] = {}
    if topic_ids:
        for assertion in records.values():
            _check_deadline(deadline)
            if (
                C1 + "Assertion" in assertion.types
                and lifecycle(assertion) == "active"
                and single_iri(assertion, RDF + "predicate") == profile.topic_predicate
                and single_iri(assertion, RDF + "object") in topic_ids
            ):
                subject = single_iri(assertion, RDF + "subject")
                if subject in reached:
                    assert subject is not None
                    topic_id = single_iri(assertion, RDF + "object")
                    assert topic_id is not None
                    carrier_dependencies.setdefault(subject, set()).update(
                        {assertion.id, *topic_dependencies[topic_id]}
                    )
    narrowing = QueryFilters(
        keywords_all=request.keywords_all,
        keywords_any=request.keywords_any,
        project_ref=request.project_ref,
    )
    keywords = {key: node for key, node in records.items() if C1 + "Keyword" in node.types}
    matched: list[dict[str, Any]] = []
    for node_id, (path, node_path) in reached.items():
        _check_deadline(deadline)
        node = records[node_id]
        relevant = (
            node_id in carrier_dependencies
            if topics
            else bool(set(profile.target_types) & set(node.types))
        )
        if relevant and evaluate_entity(node, narrowing, keywords_by_id=keywords).included:
            local_dependencies = {*path, *node_path, *carrier_dependencies.get(node_id, set())}
            if request.keywords_all or request.keywords_any:
                local_dependencies.update(
                    identifier
                    for identifier in node.properties.get(C1 + "keyword", [])
                    if isinstance(identifier, str) and identifier in keywords
                )
            matched.append(
                {
                    "node_id": node_id,
                    "distance": len(path),
                    "path": list(path),
                    "_dependencies": sorted(local_dependencies),
                }
            )
    matched.sort(
        key=lambda item: (
            item["distance"],
            normalize(primary_label(records[item["node_id"]])),
            item["node_id"],
        )
    )
    orientation = [
        {"node_ids": list(reached[item["node_id"]][1]), "path": item["path"]} for item in matched
    ]
    _check_deadline(deadline)
    return {
        "matched": matched,
        "orientation": orientation,
        "_dependencies": sorted(dependencies),
        "traversal": {
            "nodes": len(seen_nodes),
            "edges": len(seen_edges),
            "depth_limit": DEPTH_LIMIT,
            "node_limit": NODE_LIMIT,
            "edge_limit": EDGE_LIMIT,
            "truncated": False,
        },
    }
