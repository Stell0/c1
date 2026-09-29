"""A normal sized traversal page retains a usable continuation cursor."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from c1.authorization.principal import Principal
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, AssertionRecord, EntityRecord
from c1.query.plan import AuthorizedPlan
from c1.query.service import AuthorizedRecords, QueryService
from c1.runtime import Runtime

BASE = "urn:c1:instance:test:"
WORKS_FOR = C1 + "worksFor"


def _id(kind: str, value: int) -> str:
    return f"{BASE}{kind}/{UUID(int=value, version=4)}"


def test_default_traversal_page_has_compact_usable_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = EntityRecord(
        id=_id("entity", 1), labels=[LiteralValue(lexical="Start", datatype=XSD_STRING)]
    ).to_node()
    targets = [
        EntityRecord(
            id=_id("entity", index + 2),
            labels=[LiteralValue(lexical=str(index), datatype=XSD_STRING)],
        ).to_node()
        for index in range(220)
    ]
    edges = [
        AssertionRecord(
            id=_id("assertion", index + 1),
            subject=start.id,
            predicate=WORKS_FOR,
            object=target.id,
            origin="manual",
            manual_statement=True,
            attributed_to=BASE + "actor/test",
        ).to_node()
        for index, target in enumerate(targets)
    ]
    records = AuthorizedRecords({node.id: node for node in (start, *targets, *edges)}, {})
    plan = AuthorizedPlan(
        workflow_head="security-head",
        readable_scopes=frozenset(),
        authorized_ids=tuple(sorted(records)),
        scope_by_id={},
    )
    settings = SimpleNamespace(
        cursor_secret="x" * 32,
        query_candidate_limit=5000,
        max_readable_scopes=500,
        query_time_budget_ms=2000,
        instance_id="test",
    )
    runtime = cast(
        Runtime,
        SimpleNamespace(
            settings=settings,
            journal=None,
            fga=None,
            plane=None,
            knowledge=SimpleNamespace(head=AsyncMock(return_value="revision")),
            registry=ProfileRegistry(),
        ),
    )
    service = QueryService(runtime)
    monkeypatch.setattr(service, "selection", AsyncMock(return_value=(plan, {})))
    monkeypatch.setattr(service, "records", AsyncMock(return_value=records))
    monkeypatch.setattr(service.planner, "finalize", AsyncMock())
    principal = Principal("test", "alice", "human")

    async def run() -> None:
        first = await service.neighborhood(
            principal, start.id, predicates=frozenset({WORKS_FOR}), limit=200
        )
        token = first["next_cursor"]
        assert isinstance(token, str) and 0 < len(token) < 8192
        assert len(first["edges"]) == 200
        second = await service.neighborhood(
            principal, start.id, predicates=frozenset({WORKS_FOR}), limit=200, cursor=token
        )
        assert len(second["edges"]) == 20
        assert len(second["nodes"]) == 20
        assert second["next_cursor"] is None
        assert {edge["assertion_id"] for edge in first["edges"]}.isdisjoint(
            edge["assertion_id"] for edge in second["edges"]
        )

    asyncio.run(run())
