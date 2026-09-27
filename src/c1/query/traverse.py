"""Deterministic, bounded traversal of an already authorized record selection.

The caller must supply only records that passed current authorization, including
assertions and both endpoints. It must recheck that authorization before release.
This module never fetches records or treats an entity reference as permission to
read a relationship assertion.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, RDF

Direction = Literal["out", "in", "both"]
ASSERTION = C1 + "Assertion"
SUBJECT = RDF + "subject"
PREDICATE = RDF + "predicate"
OBJECT = RDF + "object"
LIFECYCLE = C1 + "lifecycle"


@dataclass(frozen=True, slots=True)
class TraversalEdge:
    assertion_id: str
    predicate: str
    subject: str
    object: str


@dataclass(frozen=True, slots=True)
class TraversalCheckpoint:
    """Unsigned BFS state. The API must sign it and bind it to its selection plan."""

    frontier: tuple[tuple[str, int, int], ...]
    visited_nodes: tuple[str, ...]
    visited_edges: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TraversalBudget:
    nodes: int
    node_limit: int
    edges: int
    edge_limit: int
    depth_limit: int


@dataclass(frozen=True, slots=True)
class TraversalResult:
    nodes: tuple[NodeRecord, ...]
    edges: tuple[TraversalEdge, ...]
    truncated: bool
    budget: TraversalBudget
    checkpoint: TraversalCheckpoint | None


def _single_iri(record: NodeRecord, predicate: str) -> str | None:
    values = record.properties.get(predicate, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def _active(record: NodeRecord) -> bool:
    values = record.properties.get(LIFECYCLE, [])
    return (
        len(values) == 1 and isinstance(values[0], LiteralValue) and values[0].lexical == "active"
    )


def _graph(
    records: dict[str, NodeRecord],
    predicates: frozenset[str],
    direction: Direction,
    deadline: float | None,
) -> dict[str, tuple[TraversalEdge, ...]]:
    adjacency: dict[str, list[TraversalEdge]] = {}
    for record in records.values():
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("traversal time budget exceeded")
        if ASSERTION not in record.types or not _active(record):
            continue
        subject = _single_iri(record, SUBJECT)
        predicate = _single_iri(record, PREDICATE)
        object_id = _single_iri(record, OBJECT)
        if (
            subject is None
            or predicate not in predicates
            or object_id is None
            or subject not in records
            or object_id not in records
            or ASSERTION in records[subject].types
            or ASSERTION in records[object_id].types
        ):
            continue
        edge = TraversalEdge(record.id, predicate, subject, object_id)
        if direction in {"out", "both"}:
            adjacency.setdefault(subject, []).append(edge)
        if direction in {"in", "both"}:
            adjacency.setdefault(object_id, []).append(edge)
    return {
        node_id: tuple(sorted(edges, key=lambda item: item.assertion_id))
        for node_id, edges in adjacency.items()
    }


def traverse_authorized(
    records: Iterable[NodeRecord],
    start_id: str,
    *,
    predicates: frozenset[str],
    direction: Direction = "out",
    depth: int = 1,
    max_nodes: int = 500,
    max_edges: int = 2000,
    limit: int | None = None,
    deadline: float | None = None,
    checkpoint: TraversalCheckpoint | None = None,
) -> TraversalResult:
    """Breadth-first traversal over readable active assertion records only.

    ``limit`` pages emitted edges inside the hard node/edge budgets. Checkpoints
    are deliberately unsigned; an API continuation must verify its signature,
    security head, selected revision and authorized selection before passing it
    back. A hard budget truncation has no continuation.
    """
    if direction not in {"out", "in", "both"}:
        raise ValueError("invalid traversal direction")
    if not 1 <= depth <= 3 or not 1 <= max_nodes <= 500 or not 1 <= max_edges <= 2000:
        raise ValueError("invalid traversal budget")
    if limit is not None and not 1 <= limit <= max_edges:
        raise ValueError("invalid traversal page limit")
    if not predicates:
        raise ValueError("at least one declared predicate is required")
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("traversal time budget exceeded")
    by_id: dict[str, NodeRecord] = {}
    for record in records:
        if record.id in by_id:
            raise ValueError("duplicate record in authorized selection")
        by_id[record.id] = record
    if start_id not in by_id or ASSERTION in by_id[start_id].types:
        raise KeyError(start_id)
    adjacency = _graph(by_id, predicates, direction, deadline)
    if checkpoint is None:
        frontier = deque([(start_id, 0, 0)])
        seen_nodes = {start_id}
        seen_edges: set[str] = set()
        page_nodes = [by_id[start_id]]
    else:
        if (
            not checkpoint.visited_nodes
            or checkpoint.visited_nodes[0] != start_id
            or not set(checkpoint.visited_nodes) <= by_id.keys()
            or len(set(checkpoint.visited_nodes)) != len(checkpoint.visited_nodes)
            or len(set(checkpoint.visited_edges)) != len(checkpoint.visited_edges)
            or len(checkpoint.visited_nodes) > max_nodes
            or len(checkpoint.visited_edges) > max_edges
            or any(
                node not in by_id or level < 0 or level >= depth or offset < 0
                for node, level, offset in checkpoint.frontier
            )
        ):
            raise ValueError("stale traversal checkpoint")
        frontier = deque(checkpoint.frontier)
        seen_nodes = set(checkpoint.visited_nodes)
        seen_edges = set(checkpoint.visited_edges)
        page_nodes = []
    page_edges: list[TraversalEdge] = []
    hard_truncated = False
    while frontier:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("traversal time budget exceeded")
        node_id, level, offset = frontier.popleft()
        adjacent = adjacency.get(node_id, ())
        if offset >= len(adjacent):
            continue
        edge = adjacent[offset]
        frontier.appendleft((node_id, level, offset + 1))
        if edge.assertion_id in seen_edges:
            continue
        next_id = edge.object if edge.subject == node_id else edge.subject
        if next_id not in seen_nodes and len(seen_nodes) >= max_nodes:
            hard_truncated = True
            continue
        if len(seen_edges) >= max_edges:
            hard_truncated = True
            break
        seen_edges.add(edge.assertion_id)
        page_edges.append(edge)
        if next_id not in seen_nodes:
            seen_nodes.add(next_id)
            page_nodes.append(by_id[next_id])
            if level + 1 < depth:
                frontier.append((next_id, level + 1, 0))
        if limit is not None and len(page_edges) >= limit:
            break
    budget = TraversalBudget(len(seen_nodes), max_nodes, len(seen_edges), max_edges, depth)
    if hard_truncated:
        return TraversalResult(tuple(page_nodes), tuple(page_edges), True, budget, None)
    pending = any(
        any(edge.assertion_id not in seen_edges for edge in adjacency.get(node_id, ())[offset:])
        for node_id, _, offset in frontier
    )
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("traversal time budget exceeded")
    if pending:
        if len(seen_edges) >= max_edges:
            return TraversalResult(tuple(page_nodes), tuple(page_edges), True, budget, None)
        if len(seen_nodes) >= max_nodes:
            possible = any(
                (edge.object if edge.subject == node_id else edge.subject) in seen_nodes
                and edge.assertion_id not in seen_edges
                for node_id, _, offset in frontier
                for edge in adjacency.get(node_id, ())[offset:]
            )
            if not possible:
                return TraversalResult(tuple(page_nodes), tuple(page_edges), True, budget, None)
        # Keep the start node first to validate a resumed traversal.
        next_checkpoint = TraversalCheckpoint(
            tuple(frontier),
            (start_id, *(node for node in sorted(seen_nodes) if node != start_id)),
            tuple(sorted(seen_edges)),
        )
        return TraversalResult(tuple(page_nodes), tuple(page_edges), True, budget, next_checkpoint)
    return TraversalResult(tuple(page_nodes), tuple(page_edges), False, budget, None)
