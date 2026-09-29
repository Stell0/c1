"""A readable topic cannot reveal an independently restricted scheme."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

import c1.query.service as query_module
from c1.authorization.models import Decision
from c1.authorization.principal import Principal
from c1.changes.models import ChangeOperation, ChangeSet, CreateOperation
from c1.changes.validation import validate_changeset
from c1.model.nodes import NodeRecord
from c1.model.records import SKOS, EntityRecord
from c1.model.references import is_independent_reference
from c1.query.filters import QueryFilters
from c1.query.plan import QueryPlanError
from c1.query.service import QueryService
from c1.runtime import Runtime
from tests.unit.m07.test_entity_kind import BASE, concept, literal, query_service, registry

PRINCIPAL = Principal("test", "dave", "human")


@pytest.mark.parametrize("readable_scheme", [False, True])
def test_list_detail_export_use_actual_scheme_pruning(
    monkeypatch: pytest.MonkeyPatch, readable_scheme: bool
) -> None:
    topic = concept("battery")
    scheme_id = str(topic.properties[SKOS + "inScheme"][0])
    scheme = EntityRecord(id=scheme_id, labels=[literal("Scheme")]).to_node()
    visible = [topic, scheme] if readable_scheme else [topic]
    service = query_service(monkeypatch, visible)
    monkeypatch.setattr(service.runtime.settings, "instance_base", BASE, raising=False)
    monkeypatch.setattr(service, "records", QueryService.records.__get__(service, QueryService))
    monkeypatch.setattr(
        query_module, "fetch_records", AsyncMock(return_value={n.id: n for n in visible})
    )
    assert is_independent_reference(SKOS + "inScheme", service.runtime.registry)

    async def run() -> None:
        listed = await service.entities(PRINCIPAL, QueryFilters(types=[SKOS + "Concept"]))
        exported = await service.export(PRINCIPAL, types=(SKOS + "Concept",))
        assert listed["count"] == exported["count"] == int(readable_scheme)
        if readable_scheme:
            detail = await service.entity(PRINCIPAL, topic.id)
            assert detail["properties"][SKOS + "inScheme"] == [scheme_id]
            assert scheme_id in json.dumps(exported)
        else:
            assert listed["items"] == exported["snapshot"]["@graph"] == []
            assert scheme_id not in json.dumps([listed, exported])
            with pytest.raises(QueryPlanError) as hidden:
                await service.entity(PRINCIPAL, topic.id)
            with pytest.raises(QueryPlanError) as absent:
                await service.entity(PRINCIPAL, BASE + "entity/nonexistent")
            assert (hidden.value.status, hidden.value.code, str(hidden.value)) == (
                absent.value.status,
                absent.value.code,
                str(absent.value),
            )

    asyncio.run(run())


@pytest.mark.parametrize("readable_scheme", [False, True])
def test_generic_resource_read_requires_scheme(readable_scheme: bool) -> None:
    topic = concept("battery")
    scheme_id = str(topic.properties[SKOS + "inScheme"][0])

    async def authorize(_principal: Principal, identifier: str) -> Decision:
        return Decision(
            identifier == topic.id or (readable_scheme and identifier == scheme_id),
            "allowed" if readable_scheme else "denied",
        )

    runtime = cast(
        Runtime,
        SimpleNamespace(
            registry=registry(),
            settings=SimpleNamespace(instance_base=BASE),
            journal=SimpleNamespace(
                list=AsyncMock(return_value=[]), head=AsyncMock(return_value="security")
            ),
            plane=SimpleNamespace(check_read=authorize),
            knowledge=SimpleNamespace(get_record=AsyncMock(return_value=topic)),
        ),
    )

    async def run() -> None:
        result = await Runtime.read(runtime, PRINCIPAL, topic.id)
        assert result == (topic if readable_scheme else None)

    asyncio.run(run())


@pytest.mark.parametrize("readable_scheme", [False, True])
def test_topic_write_requires_resolved_authorized_scheme(readable_scheme: bool) -> None:
    topic = concept("battery")
    scheme_id = str(topic.properties[SKOS + "inScheme"][0])
    scheme = EntityRecord(id=scheme_id, labels=[literal("Scheme")]).to_node()
    changeset = ChangeSet(
        id="topic-create",
        author="dave",
        base_revision="revision",
        operations=[CreateOperation(record=topic.model_dump(mode="json"), scope_id="shared")],
        created="2026-09-28T00:00:00Z",
        updated="2026-09-28T00:00:00Z",
    )
    requested: list[str] = []

    async def resolve(identifier: str, _revision: str) -> NodeRecord | None:
        requested.append(identifier)
        return scheme if readable_scheme else None

    async def allow(_operation: ChangeOperation) -> Decision:
        return Decision(True, "allowed")

    async def run() -> None:
        result = await validate_changeset(
            changeset, registry=registry(), resolve_reference=resolve, permission_preview=allow
        )
        assert requested == [scheme_id]
        assert result.accepted is readable_scheme
        assert [item.code for item in result.diagnostics] == (
            [] if readable_scheme else ["C1-CS-010"]
        )

    asyncio.run(run())
