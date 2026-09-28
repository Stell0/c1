"""DocumentPart binding defaults and document move authorization."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.models import Binding, Decision
from c1.authorization.operations import WriterGate
from c1.authorization.principal import Principal
from c1.changes.apply import ChangeService
from c1.changes.digest import request_digest
from c1.changes.models import ChangeOperation, ChangeSet, CreateOperation, ReplaceOperation
from c1.model.nodes import NodeRecord

DOCUMENT = "urn:c1:ns:core#Document"
PART = "urn:c1:ns:core#DocumentPart"
PART_OF = "urn:c1:ns:core#partOfDocument"
P = Principal("local", "author", "human")


def _part(
    document: str, identifier: str = "urn:c1:part", order: str | None = None
) -> dict[str, object]:
    properties: dict[str, object] = {PART_OF: [document]}
    if order is not None:
        properties["urn:c1:ns:core#orderKey"] = [
            {"lexical": order, "datatype": "http://www.w3.org/2001/XMLSchema#string"}
        ]
    return {"id": identifier, "types": [PART], "properties": properties}


def _service() -> ChangeService:
    service = object.__new__(ChangeService)
    service.plane = AsyncMock()
    service.knowledge = AsyncMock()
    service.registry = AsyncMock()
    cast(Any, service.plane).check_read.return_value = Decision(True, "allowed")
    cast(Any, service.plane).check_scope.return_value = Decision(True, "allowed")
    cast(Any, service.plane).check_operation.return_value = Decision(True, "allowed")
    return service


@pytest.mark.parametrize("properties", [[], None, "not an object"])
def test_malformed_inherited_part_is_a_validation_error(properties: object) -> None:
    with pytest.raises(ValueError, match="properties must be an object"):
        CreateOperation(
            record={"id": "urn:c1:part", "types": [PART], "properties": properties},
            scope_id="team",
            inherited_from="urn:c1:doc",
        )


def test_part_default_is_normalized_before_proposal_digest() -> None:
    async def case() -> None:
        service = _service()
        document = "urn:c1:doc"
        cast(Any, service.plane).bindings.return_value = Binding(
            resource_id=document, scope_id="team", state="active", operation_id="setup"
        )
        raw = CreateOperation(record=_part(document))
        normalized = await service._normalize_operations(P, [raw])
        assert normalized == [
            raw.model_copy(update={"scope_id": "team", "inherited_from": document})
        ]
        proposal = ChangeSet(
            id="urn:c1:proposal",
            author=P.id,
            base_revision="branch:base",
            operations=normalized,
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )
        assert proposal.request_digest == request_digest("branch:base", normalized, None)
        assert proposal.request_digest != request_digest("branch:base", [raw], None)

    asyncio.run(case())


def test_default_binding_request_replays_after_parent_authority_changes(tmp_path: Path) -> None:
    async def case() -> None:
        service = _service()
        service.settings = cast(
            Any,
            SimpleNamespace(instance_base="urn:c1:instance:test:", knowledge_database="test"),
        )
        service.writer = WriterGate(tmp_path / "writer.lock")
        service.journal = cast(Any, SimpleNamespace(get=AsyncMock(return_value=None)))
        save = AsyncMock()
        cast(Any, service)._save = save
        document = "urn:c1:doc"
        cast(Any, service.plane).bindings.return_value = Binding(
            resource_id=document, scope_id="public", state="active", operation_id="setup"
        )
        body = SimpleNamespace(
            base_revision="base",
            operations=[CreateOperation(record=_part(document))],
            rationale="Create a default-inheriting part",
            restores_from_revision=None,
        )
        original = await service.create(P, body, "same-request")
        reservation = save.call_args.args[1][2]
        assert reservation["digest"] == request_digest("base", body.operations, body.rationale)
        assert original["operations"][0]["scope_id"] == "public"
        cast(Any, service.journal).get.return_value = reservation
        cast(Any, service.plane).check_read.return_value = Decision(False, "permission_denied")
        cast(Any, service.plane).bindings.reset_mock()
        replay = await service.create(P, body, "same-request")
        assert replay == {**original, "replayed": True}
        cast(Any, service.plane).bindings.assert_not_called()
        assert save.await_count == 1

    asyncio.run(case())


def test_part_can_inherit_document_created_in_same_proposal() -> None:
    async def case() -> None:
        service = _service()
        document = "urn:c1:new-document"
        operations: list[ChangeOperation] = [
            CreateOperation(
                record={"id": document, "types": [DOCUMENT], "properties": {}},
                scope_id="team",
            ),
            CreateOperation(record=_part(document)),
        ]
        normalized = await service._normalize_operations(P, operations)
        assert isinstance(normalized[1], CreateOperation)
        assert normalized[1].scope_id == "team"
        assert normalized[1].inherited_from == document
        cast(Any, service.plane).bindings.assert_not_called()

    asyncio.run(case())


def test_reviewer_can_see_validated_staged_document_and_part() -> None:
    async def case() -> None:
        service = _service()
        document = "urn:c1:new-document"
        changeset = ChangeSet(
            id="urn:c1:proposal",
            author="user:local.service-author",
            base_revision="branch:base",
            operations=[
                CreateOperation(
                    record={"id": document, "types": [DOCUMENT], "properties": {}},
                    scope_id="team",
                ),
                CreateOperation(record=_part(document), scope_id="team", inherited_from=document),
            ],
            state="validated",
            validation_report_id="urn:c1:report",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )
        assert await service._visible(P, changeset)
        cast(Any, service.plane).check_read.assert_not_called()
        cast(Any, service.plane).check_scope.assert_any_await(P, "review", "team")

    asyncio.run(case())


def test_part_move_requires_contribute_on_both_documents() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.knowledge).get_record.return_value = NodeRecord.model_validate(
            _part("urn:c1:old")
        )
        operation = ReplaceOperation(
            resource_id="urn:c1:part", record=_part("urn:c1:new"), reason="move"
        )
        cast(Any, service.plane).check_operation.side_effect = lambda _p, _action, target, **_kw: (
            Decision(False, "permission_denied")
            if target == "urn:c1:new"
            else Decision(True, "allowed")
        )
        denied = await service._permission(P, operation, review=False)
        assert not denied.allowed
        checks = cast(Any, service.plane).check_operation.await_args_list
        assert checks[-2].args[2] == "urn:c1:old"
        assert checks[-1].args[2] == "urn:c1:new"

    asyncio.run(case())


def test_part_author_must_read_target_document() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.plane).check_read.return_value = Decision(False, "permission_denied")
        operation = CreateOperation(record=_part("urn:c1:protected"), scope_id="team")
        denied = await service._permission(P, operation, review=False)
        assert not denied.allowed

    asyncio.run(case())


def test_independent_part_create_requires_contribute_on_target_document() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.plane).check_operation.side_effect = lambda _p, _action, _target, **_kw: (
            Decision(False, "permission_denied")
        )
        operation = CreateOperation(record=_part("urn:c1:document"), scope_id="team")
        denied = await service._permission(P, operation, review=False)
        assert not denied.allowed
        cast(Any, service.plane).check_operation.assert_awaited_with(
            P, "contribute", "urn:c1:document"
        )

    asyncio.run(case())


def test_part_create_review_requires_target_document_review() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.plane).check_operation.return_value = Decision(False, "permission_denied")
        operation = CreateOperation(record=_part("urn:c1:document"), scope_id="independent")
        denied = await service._permission(P, operation, review=True)
        assert not denied.allowed
        cast(Any, service.plane).check_operation.assert_awaited_with(P, "review", "urn:c1:document")

    asyncio.run(case())


def test_part_move_review_requires_both_document_reviews() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.knowledge).get_record.return_value = NodeRecord.model_validate(
            _part("urn:c1:old")
        )
        operation = ReplaceOperation(
            resource_id="urn:c1:part", record=_part("urn:c1:new"), reason="move"
        )
        cast(Any, service.plane).check_operation.side_effect = lambda _p, _action, target, **_kw: (
            Decision(False, "permission_denied")
            if target == "urn:c1:new"
            else Decision(True, "allowed")
        )
        denied = await service._permission(P, operation, review=True)
        assert not denied.allowed
        checks = cast(Any, service.plane).check_operation.await_args_list
        assert [(call.args[1], call.args[2]) for call in checks] == [
            ("review", "urn:c1:part"),
            ("review", "urn:c1:old"),
            ("review", "urn:c1:new"),
        ]

    asyncio.run(case())


def test_part_reorder_requires_document_review() -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.knowledge).get_record.return_value = NodeRecord.model_validate(
            _part("urn:c1:document", order="A")
        )
        operation = ReplaceOperation(
            resource_id="urn:c1:part",
            record=_part("urn:c1:document", order="B"),
            reason="reorder",
        )
        cast(Any, service.plane).check_operation.side_effect = lambda _p, _action, target, **_kw: (
            Decision(False, "permission_denied")
            if target == "urn:c1:document"
            else Decision(True, "allowed")
        )
        denied = await service._permission(P, operation, review=True)
        assert not denied.allowed
        cast(Any, service.plane).check_operation.assert_any_await(P, "review", "urn:c1:document")

    asyncio.run(case())


def test_part_inheritance_cannot_name_another_document() -> None:
    with pytest.raises(ValueError, match="inheritance must target its document"):
        CreateOperation(
            record=_part("urn:c1:document"),
            scope_id="team",
            inherited_from="urn:c1:different-document",
        )


@pytest.mark.parametrize("review", [False, True])
def test_part_retyping_cannot_bypass_document_structure(review: bool) -> None:
    async def case() -> None:
        service = _service()
        cast(Any, service.knowledge).get_record.return_value = NodeRecord.model_validate(
            _part("urn:c1:protected-document")
        )
        operation = ReplaceOperation(
            resource_id="urn:c1:part",
            record={"id": "urn:c1:part", "types": ["urn:c1:ns:core#Entity"], "properties": {}},
            reason="Attempt to detach a part by changing its storage class",
        )
        denied = await service._permission(P, operation, review=review)
        assert not denied.allowed
        cast(Any, service.knowledge).get_record.assert_awaited_once()

    asyncio.run(case())
