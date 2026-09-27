"""Probe provisioning authorizes before checking canonical ID collisions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from c1.authorization.audit import Audit
from c1.authorization.bindings import Bindings
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGA
from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Decision, Scope
from c1.authorization.operations import SecurityOperations
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import Terminus

_C1 = "urn:c1:ns:core#"
_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
_RESOURCE = "urn:c1:probe:entity/privacy"
_SCOPE = "scope-new"
_PRINCIPAL = Principal("c1-dev", "alice", "human")


def _record() -> NodeRecord:
    return NodeRecord(
        id=_RESOURCE,
        types=[_C1 + "Entity"],
        properties={
            _LABEL: [LiteralValue(lexical="Privacy", datatype=_XSD_STRING)],
            _C1 + "lifecycle": [LiteralValue(lexical="active", datatype=_XSD_STRING)],
        },
    )


def _operations(tmp_path: Path) -> Any:
    settings = cast(
        Settings,
        SimpleNamespace(
            instance_id="dev",
            enable_probe_routes=True,
            lock_path=tmp_path / "writer.lock",
        ),
    )
    plane = MagicMock(spec=AuthorizationPlane)
    plane.current = MagicMock(spec=Bindings)
    plane.current.scope.return_value = Scope(id=_SCOPE, label="New scope", state="active")
    return SecurityOperations(
        settings=settings,
        journal=MagicMock(spec=Journal),
        fga=MagicMock(spec=FGA),
        plane=plane,
        knowledge=MagicMock(spec=Terminus),
        registry=ProfileRegistry(),
        audit=MagicMock(spec=Audit),
    )


@pytest.mark.parametrize("binding_exists", [False, True])
def test_scope_denial_precedes_existing_id_lookup(tmp_path: Path, binding_exists: bool) -> None:
    async def case() -> None:
        operations = _operations(tmp_path)
        operations.plane.check_scope.return_value = Decision(False, "permission_denied")
        operations.journal.get.return_value = {"resource_id": _RESOURCE} if binding_exists else None
        try:
            with pytest.raises(SecurityError) as caught:
                await operations.provision(_PRINCIPAL, _record(), scope_id=_SCOPE)
            assert (caught.value.status, caught.value.reason) == (403, "authorization_denied")
            operations.journal.get.assert_not_awaited()
            operations.knowledge.get_record.assert_not_awaited()
        finally:
            operations.writer.close()

    asyncio.run(case())


@pytest.mark.parametrize(
    ("read_allowed", "expected_status", "expected_reason"),
    [(False, 404, "not_found"), (True, 409, "resource_exists")],
)
def test_existing_id_response_depends_only_on_current_read_permission(
    tmp_path: Path, read_allowed: bool, expected_status: int, expected_reason: str
) -> None:
    async def case() -> None:
        operations = _operations(tmp_path)
        operations.plane.check_scope.return_value = Decision(True, "allowed")
        operations.plane.check_read.return_value = Decision(
            read_allowed, "allowed" if read_allowed else "permission_denied"
        )
        operations.journal.get.return_value = Binding(
            resource_id=_RESOURCE,
            scope_id="scope-hidden",
            state="active",
            operation_id="earlier-operation",
        ).model_dump(mode="json")
        try:
            with pytest.raises(SecurityError) as caught:
                await operations.provision(_PRINCIPAL, _record(), scope_id=_SCOPE)
            assert (caught.value.status, caught.value.reason) == (
                expected_status,
                expected_reason,
            )
            operations.plane.check_read.assert_awaited_once_with(_PRINCIPAL, _RESOURCE)
            operations.knowledge.get_record.assert_not_awaited()
        finally:
            operations.writer.close()

    asyncio.run(case())


def test_orphan_knowledge_collision_is_generic_not_found(tmp_path: Path) -> None:
    async def case() -> None:
        operations = _operations(tmp_path)
        operations.plane.check_scope.return_value = Decision(True, "allowed")
        operations.journal.get.return_value = None
        operations.knowledge.get_record.return_value = _record()
        try:
            with pytest.raises(SecurityError) as caught:
                await operations.provision(_PRINCIPAL, _record(), scope_id=_SCOPE)
            assert (caught.value.status, caught.value.reason) == (404, "not_found")
            operations.plane.check_read.assert_not_awaited()
            operations.journal.save_many.assert_not_awaited()
        finally:
            operations.writer.close()

    asyncio.run(case())
