"""M05 traversal and export over a fully authorized synthetic selection."""

from __future__ import annotations

import time

import pytest

from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, AssertionRecord, EntityRecord
from c1.query.explain import explain_matches
from c1.query.export import export_authorized
from c1.query.traverse import traverse_authorized

BASE = "urn:c1:instance:test:"
WORKS_FOR = C1 + "worksFor"


def entity(name: str) -> NodeRecord:
    return EntityRecord(
        id=BASE + "entity/" + name,
        labels=[LiteralValue(lexical=name, datatype=XSD_STRING)],
    ).to_node()


def edge(name: str, subject: NodeRecord, target: NodeRecord, *, active: bool = True) -> NodeRecord:
    return AssertionRecord(
        id=BASE + "assertion/" + name,
        subject=subject.id,
        predicate=WORKS_FOR,
        object=target.id,
        origin="manual",
        manual_statement=True,
        attributed_to=BASE + "actor/test",
        lifecycle="active" if active else "retracted",
    ).to_node()


def test_hidden_assertion_or_endpoint_cannot_change_neighborhood() -> None:
    a, b, c, hidden = (entity(name) for name in "abch")
    visible = edge("ab", a, b)
    hidden_link = edge("bc", b, c)
    hidden_target = edge("ah", a, hidden)
    baseline = traverse_authorized(
        [a, b, c, visible], a.id, predicates=frozenset({WORKS_FOR}), depth=3
    )
    assert [item.id for item in baseline.nodes] == [a.id, b.id]
    assert [item.assertion_id for item in baseline.edges] == [visible.id]
    assert baseline.truncated is False
    # A readable edge without its readable target is not traversable either.
    assert (
        traverse_authorized(
            [a, b, c, visible, hidden_target],
            a.id,
            predicates=frozenset({WORKS_FOR}),
            depth=3,
        )
        == baseline
    )
    assert (
        traverse_authorized(
            [a, b, c, visible, hidden_link],
            a.id,
            predicates=frozenset({WORKS_FOR}),
            depth=3,
        )
        .nodes[-1]
        .id
        == c.id
    )


def test_direction_depth_inactive_and_deterministic_order() -> None:
    a, b, c = (entity(name) for name in "abc")
    ab = edge("z", a, b)
    ac = edge("a", a, c)
    inactive = edge("inactive", c, b, active=False)
    records = [inactive, b, ab, a, c, ac]
    outward = traverse_authorized(records, a.id, predicates=frozenset({WORKS_FOR}), depth=1)
    assert [item.assertion_id for item in outward.edges] == [ac.id, ab.id]
    assert [item.id for item in outward.nodes] == [a.id, c.id, b.id]
    inward = traverse_authorized(records, b.id, predicates=frozenset({WORKS_FOR}), direction="in")
    assert [item.id for item in inward.nodes] == [b.id, a.id]
    assert not traverse_authorized(
        records, a.id, predicates=frozenset({C1 + "unrelated"}), depth=3
    ).edges


def test_edge_page_checkpoint_and_hard_node_budget() -> None:
    a, b, c = (entity(name) for name in "abc")
    ab, bc = edge("ab", a, b), edge("bc", b, c)
    records = [a, b, c, ab, bc]
    first = traverse_authorized(records, a.id, predicates=frozenset({WORKS_FOR}), depth=3, limit=1)
    assert first.truncated and first.checkpoint is not None
    assert [item.id for item in first.nodes] == [a.id, b.id]
    second = traverse_authorized(
        records,
        a.id,
        predicates=frozenset({WORKS_FOR}),
        depth=3,
        limit=1,
        checkpoint=first.checkpoint,
    )
    assert [item.id for item in second.nodes] == [c.id]
    assert [item.assertion_id for item in second.edges] == [bc.id]
    assert second.budget.nodes == 3 and second.budget.edges == 2
    bounded = traverse_authorized(
        records, a.id, predicates=frozenset({WORKS_FOR}), depth=3, max_nodes=2
    )
    assert bounded.truncated and bounded.checkpoint is None
    assert [item.id for item in bounded.nodes] == [a.id, b.id]
    with pytest.raises(ValueError, match="stale traversal checkpoint"):
        traverse_authorized(
            [a, c, ab, bc],
            a.id,
            predicates=frozenset({WORKS_FOR}),
            depth=3,
            checkpoint=first.checkpoint,
        )


def test_invalid_limits_and_deadline_fail_without_result() -> None:
    a = entity("a")
    with pytest.raises(ValueError):
        traverse_authorized([a], a.id, predicates=frozenset({WORKS_FOR}), depth=4)
    with pytest.raises(ValueError):
        traverse_authorized([a], a.id, predicates=frozenset({WORKS_FOR}), max_nodes=501)
    with pytest.raises(ValueError):
        traverse_authorized([a], a.id, predicates=frozenset({WORKS_FOR}), max_edges=2001)
    with pytest.raises(ValueError):
        traverse_authorized([a], a.id, predicates=frozenset({WORKS_FOR}), limit=0)
    with pytest.raises(TimeoutError):
        traverse_authorized(
            [a], a.id, predicates=frozenset({WORKS_FOR}), deadline=time.monotonic() - 1
        )


def test_export_and_explain_use_only_selected_ids() -> None:
    a, hidden = entity("a"), entity("hidden")
    exported = export_authorized([a], authorized_ids=frozenset({a.id}))
    assert [item["@id"] for item in exported["@graph"]] == [a.id]
    with pytest.raises(ValueError, match="outside the authorized selection"):
        export_authorized([a, hidden], authorized_ids=frozenset({a.id}))
    assert explain_matches({a.id: ["label", "types", "label"], hidden.id: ["secret"]}, [a.id]) == (
        {"id": a.id, "matched_filters": ["label", "types"]},
    )
