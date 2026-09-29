"""Publication, checkpoint privacy, and canonical context orientation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.principal import Principal
from c1.context.errors import ContextError
from c1.context.profiles import ContextProfileCatalog
from c1.context.request import ContextRequest
from c1.context.service import ContextService, _checkpoint, _orientation
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, SKOS, EntityRecord
from c1.query.cursor import CursorCodec
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.runtime import Runtime


def entity(identifier: str, label: str = "Tesla") -> NodeRecord:
    return EntityRecord(
        id="urn:test:" + identifier, labels=[LiteralValue(lexical=label, datatype=XSD_STRING)]
    ).to_node()


def plan(records: dict[str, NodeRecord], **bindings: str) -> AuthorizedPlan:
    return AuthorizedPlan(
        "security-head",
        frozenset(),
        tuple(sorted(records)),
        {identifier: bindings.get(identifier, "scope-a") for identifier in records},
    )


def harness(records: dict[str, NodeRecord]) -> tuple[ContextService, Any, AuthorizedPlan]:
    original = plan(records)
    query = SimpleNamespace(
        selection=AsyncMock(return_value=(original, {})),
        records=AsyncMock(return_value=AuthorizedRecords(records, {})),
        planner=SimpleNamespace(finalize=AsyncMock()),
        codec=CursorCodec("x" * 32),
    )
    runtime = cast(
        Runtime,
        SimpleNamespace(
            settings=SimpleNamespace(query_time_budget_ms=2000),
            context_catalog=ContextProfileCatalog,
            registry=ProfileRegistry(),
            query=query,
            knowledge=SimpleNamespace(head=AsyncMock(return_value="branch:fixed")),
        ),
    )
    return ContextService(runtime), query, original


def request(**values: Any) -> ContextRequest:
    return ContextRequest.model_validate(
        {
            "profile": "graph-context",
            "profile_version": "1",
            "anchor": {"label": "Tesla"},
            **values,
        }
    )


def test_ambiguity_finalizes_original_plan_and_hides_internal_dependencies() -> None:
    nodes = [entity("a"), entity("b")]
    service, query, original = harness({item.id: item for item in nodes})
    principal = Principal("test", "alice", "human")
    result = asyncio.run(service.build(principal, request()))
    assert result["outcome"] == "ambiguous"
    assert "markdown" not in result and "structured" not in result
    assert len(result["anchor_resolution"]["candidates"]) == 2
    assert not any(key.startswith("_") for key in result["anchor_resolution"])
    assert not any(key.startswith("_") for key in result["topic_resolution"])
    assert query.planner.finalize.await_args.args == (principal, original)


def test_finalization_failure_prevents_resolved_publication() -> None:
    node = entity("a")
    service, query, original = harness({node.id: node})
    principal = Principal("test", "alice", "human")
    query.planner.finalize.side_effect = QueryPlanError(409, "C1-QY-051", "restart_required")
    with pytest.raises(QueryPlanError, match="restart_required"):
        asyncio.run(service.build(principal, request()))
    assert query.planner.finalize.await_args.args == (principal, original)


def test_unknown_or_unreadable_anchor_has_same_failure() -> None:
    service, _, _ = harness({})
    with pytest.raises(ContextError) as error:
        asyncio.run(
            service.build(
                Principal("test", "alice", "human"), request(anchor={"id": "urn:test:unreadable"})
            )
        )
    assert (error.value.status, error.value.code, error.value.reason) == (
        404,
        "C1-CX-404",
        "not_found",
    )


def test_current_head_and_selection_overlap_before_retrieval() -> None:
    node = entity("a")
    service, query, original = harness({node.id: node})

    async def run() -> None:
        head_started, plan_started = asyncio.Event(), asyncio.Event()

        async def head() -> str:
            head_started.set()
            await plan_started.wait()
            return "branch:fixed"

        async def selection(*_args: Any, **_kwargs: Any) -> Any:
            plan_started.set()
            await head_started.wait()
            return original, {}

        cast(Any, service.runtime.knowledge).head = AsyncMock(side_effect=head)
        query.selection.side_effect = selection
        result = await service.build(Principal("test", "alice", "human"), request())
        assert result["revision"] == "branch:fixed"
        query.records.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("failed_read", ["head", "selection"])
def test_initial_read_failure_cancels_and_awaits_sibling(failed_read: str) -> None:
    service, query, _ = harness({})

    async def run() -> None:
        sibling_started, sibling_finished = asyncio.Event(), asyncio.Event()

        async def failing(*_args: Any, **_kwargs: Any) -> Any:
            await sibling_started.wait()
            raise QueryPlanError(503, "C1-QY-054", "read_unavailable")

        async def sibling(*_args: Any, **_kwargs: Any) -> Any:
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                sibling_finished.set()

        cast(Any, service.runtime.knowledge).head = AsyncMock(
            side_effect=failing if failed_read == "head" else sibling
        )
        query.selection.side_effect = failing if failed_read == "selection" else sibling
        with pytest.raises(QueryPlanError, match="read_unavailable"):
            await service.build(Principal("test", "alice", "human"), request())
        assert sibling_finished.is_set()
        query.records.assert_not_awaited()

    asyncio.run(run())


def test_pinned_revision_does_not_read_current_head() -> None:
    node = entity("a")
    service, query, _ = harness({node.id: node})
    result = asyncio.run(
        service.build(Principal("test", "alice", "human"), request(revision="branch:pinned"))
    )
    assert result["revision"] == "branch:pinned"
    cast(Any, service.runtime.knowledge).head.assert_not_awaited()
    assert query.records.await_args.args[1] == "branch:pinned"


def test_checkpoint_tracks_used_bindings_without_unrelated_security_changes() -> None:
    records = {
        item.id: item
        for item in [
            entity("anchor"),
            entity("topic"),
            entity("keyword"),
            entity("carrier"),
            entity("unused"),
        ]
    }
    units = [
        {"node_id": "urn:test:anchor", "_dependencies": ["urn:test:keyword", "urn:test:carrier"]}
    ]
    public = [{"node_id": "urn:test:anchor", "claims": [{"value": "existing"}]}]
    interpretation = {"anchor": {"id": "urn:test:anchor"}, "topics": [{"id": "urn:test:topic"}]}
    initial = _checkpoint(units, public, 1, interpretation, records, plan(records))
    for used in ["urn:test:keyword", "urn:test:carrier"]:
        assert (
            _checkpoint(
                units,
                public,
                1,
                interpretation,
                records,
                plan(records, **{used: "still-readable-scope-b"}),
            )
            != initial
        )
    assert (
        _checkpoint(
            units,
            public,
            1,
            interpretation,
            records,
            plan(records, **{"urn:test:unused": "scope-b"}),
        )
        == initial
    )
    assert (
        _checkpoint(
            units, public, 1, interpretation, records, plan(records), frozenset({"urn:test:unused"})
        )
        != initial
    )
    edited = [{"node_id": "urn:test:anchor", "claims": [{"value": "changed"}]}]
    assert _checkpoint(units, edited, 1, interpretation, records, plan(records)) != initial


def test_orientation_canonicalizes_set_valued_labels_and_types() -> None:
    node = entity("anchor").model_copy(
        update={
            "types": ["urn:test:Z", C1 + "Entity"],
            "properties": {
                SKOS + "prefLabel": [
                    LiteralValue(lexical=value, datatype=XSD_STRING) for value in ["Zulu", "alpha"]
                ]
            },
        }
    )
    selection = {"orientation": [{"node_ids": [node.id], "path": []}]}
    baseline = _orientation(selection, {node.id: node})
    permuted = node.model_copy(
        update={
            "types": list(reversed(node.types)),
            "properties": {SKOS + "prefLabel": list(reversed(node.properties[SKOS + "prefLabel"]))},
        }
    )
    assert _orientation(selection, {node.id: permuted}) == baseline
    assert baseline[0]["nodes"][0]["label"] == "alpha"
