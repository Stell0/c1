"""Large readable documents remain pageable after reconstruction is refused."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from c1.authorization.principal import Principal
from c1.documents.service import DocumentsService
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1
from c1.query.cursor import CursorCodec
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.runtime import Runtime


def test_reconstruction_limit_preserves_search_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = NodeRecord(
        id=f"urn:c1:instance:test:document/{UUID(int=1, version=4)}",
        types=[C1 + "Document"],
        properties={},
    )
    parts = [
        NodeRecord(
            id=f"urn:c1:instance:test:document-part/{UUID(int=index + 1, version=4)}",
            types=[C1 + "DocumentPart"],
            properties={
                C1 + "partOfDocument": [document.id],
                C1 + "orderKey": [LiteralValue(lexical="A", datatype=XSD_STRING)],
                C1 + "text": [LiteralValue(lexical="needle", datatype=XSD_STRING)],
            },
        )
        for index in range(2001)
    ]
    records = AuthorizedRecords({node.id: node for node in (document, *parts)}, {})
    plan = AuthorizedPlan("security-head", frozenset(), tuple(records), {})
    runtime = cast(
        Runtime,
        SimpleNamespace(
            settings=SimpleNamespace(instance_id="test"),
            query=SimpleNamespace(codec=CursorCodec(b"x" * 32)),
        ),
    )
    service = DocumentsService(runtime)
    monkeypatch.setattr(service, "_selection", AsyncMock(return_value=(plan, records, "r1", 0)))
    monkeypatch.setattr(service, "_finish", AsyncMock())
    principal = Principal("test", "alice", "human")

    async def run() -> None:
        found = await service.list(principal, text_contains="needle")
        assert found["count"] == 1
        first = await service.parts(principal, document.id, limit=200)
        assert first["count"] == 2001 and len(first["items"]) == 200
        second = await service.parts(principal, document.id, limit=200, cursor=first["next_cursor"])
        assert len(second["items"]) == 200
        assert {part["part_id"] for part in first["items"]}.isdisjoint(
            part["part_id"] for part in second["items"]
        )
        for request in (service.detail, service.render, service.export):
            with pytest.raises(QueryPlanError) as caught:
                await request(principal, document.id)
            assert caught.value.code == "C1-DC-006"

    asyncio.run(run())
