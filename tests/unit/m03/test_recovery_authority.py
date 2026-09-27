"""Recovery confirms completed revocations and rechecks current probe authority."""

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
from c1.authorization.fga import FGA, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Operation, Scope
from c1.authorization.operations import SecurityOperations
from c1.authorization.plane import AuthorizationPlane
from c1.config import Settings
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import Terminus

_ACTOR = "user:c1-dev.alice"
_RESOURCE = "urn:c1:probe:entity/one"
_SCOPE = "scope-one"


def _operation(kind: str, *, payload: dict[str, object] | None = None) -> Operation:
    return Operation.model_validate(
        {
            "id": "operation-one",
            "kind": kind,
            "actor": _ACTOR,
            "target": _RESOURCE if kind == "probe_revision" else _SCOPE,
            "state": "pending",
            "targets": [_RESOURCE] if kind == "probe_revision" else [],
            "payload": payload or {},
            "created": "2026-09-27T00:00:00Z",
            "updated": "2026-09-27T00:00:00Z",
        }
    )


def _operations() -> Any:
    settings = cast(
        Settings,
        SimpleNamespace(instance_id="dev", lock_path=Path("/tmp/c1-recovery-unit.lock")),
    )
    plane = MagicMock(spec=AuthorizationPlane)
    plane.current = MagicMock(spec=Bindings)
    return SecurityOperations(
        settings=settings,
        journal=MagicMock(spec=Journal),
        fga=MagicMock(spec=FGA),
        plane=plane,
        knowledge=MagicMock(spec=Terminus),
        registry=ProfileRegistry(),
        audit=MagicMock(spec=Audit),
    )


@pytest.mark.parametrize("kind", ["membership", "instance_grant"])
def test_recovery_confirms_already_applied_self_revocation(kind: str) -> None:
    async def case() -> None:
        operations = _operations()
        op = _operation(
            kind,
            payload={"member": _ACTOR, "role": "access_admin", "grant": False},
        )
        operations.fga.read.return_value = []

        await operations._reconcile(op)

        assert op.state == "applied"
        operations.fga.ensure_tuple.assert_not_awaited()
        operations.fga.check.assert_not_awaited()
        operations.journal.save_many.assert_awaited_once()
        expected_object = scope_object(_SCOPE) if kind == "membership" else "instance:dev"
        operations.fga.read.assert_awaited_once_with(
            user=_ACTOR, relation="access_admin", object=expected_object
        )

    asyncio.run(case())


def test_recovery_does_not_revoke_when_actor_lost_authority_first() -> None:
    async def case() -> None:
        operations = _operations()
        op = _operation(
            "membership",
            payload={"member": "user:c1-dev.bob", "role": "reader", "grant": False},
        )
        operations.fga.read.return_value = [("user:c1-dev.bob", "reader", scope_object(_SCOPE))]
        operations.plane.current.scope.return_value = Scope(
            id=_SCOPE, label="Scope", state="active"
        )
        operations.fga.check.return_value = False

        with pytest.raises(SecurityError, match="recovery_authority_unavailable"):
            await operations._reconcile(op)

        assert op.state == "pending"
        operations.fga.ensure_tuple.assert_not_awaited()
        operations.journal.save_many.assert_not_awaited()

    asyncio.run(case())


@pytest.mark.parametrize(
    ("bound_to", "other_pending"),
    [
        ([], False),
        ([scope_object("other-scope")], False),
        ([scope_object(_SCOPE)] * 2, False),
        ([scope_object(_SCOPE)], True),
    ],
)
def test_probe_recovery_refuses_inconsistent_or_pending_binding(
    bound_to: list[str], other_pending: bool
) -> None:
    async def case() -> None:
        operations = _operations()
        op = _operation("probe_revision")
        operations.plane.bindings.return_value = Binding(
            resource_id=_RESOURCE,
            scope_id=_SCOPE,
            state="active",
            operation_id="original-operation",
        )
        operations.plane.current.pending.return_value = other_pending
        operations.plane.current.scope.return_value = Scope(
            id=_SCOPE, label="Scope", state="active"
        )
        operations.fga.bindings.return_value = bound_to
        operations.fga.check.return_value = True

        with pytest.raises(SecurityError, match="recovery_authority_unavailable"):
            await operations._reconcile(op)

        assert op.state == "pending"
        operations.knowledge.replace_records.assert_not_awaited()
        operations.plane.current.pending.assert_awaited_once_with(
            _RESOURCE, _SCOPE, excluding=op.id
        )

    asyncio.run(case())


def test_probe_recovery_requires_resource_permission_and_excludes_own_pending() -> None:
    async def case() -> None:
        operations = _operations()
        op = _operation("probe_revision")
        operations.plane.bindings.return_value = Binding(
            resource_id=_RESOURCE,
            scope_id=_SCOPE,
            state="active",
            operation_id="original-operation",
        )
        operations.plane.current.pending.return_value = False
        operations.plane.current.scope.return_value = Scope(
            id=_SCOPE, label="Scope", state="active"
        )
        operations.fga.bindings.return_value = [scope_object(_SCOPE)]
        operations.fga.check.side_effect = lambda _actor, relation, _object: (
            relation == "contributor"
        )

        assert not await operations._authorized(op)
        operations.plane.current.pending.assert_awaited_once_with(
            _RESOURCE, _SCOPE, excluding=op.id
        )
        operations.fga.check.assert_any_await(_ACTOR, "can_contribute", resource_object(_RESOURCE))
        operations.fga.check.side_effect = None
        operations.fga.check.return_value = True
        assert await operations._authorized(op)

    asyncio.run(case())


@pytest.mark.parametrize(
    ("binding_state", "scope_state"),
    [("transitioning", "active"), ("active", "retired")],
)
def test_probe_recovery_refuses_inactive_binding_or_scope(
    binding_state: str, scope_state: str
) -> None:
    async def case() -> None:
        operations = _operations()
        op = _operation("probe_revision")
        operations.plane.bindings.return_value = Binding.model_validate(
            {
                "resource_id": _RESOURCE,
                "scope_id": _SCOPE,
                "state": binding_state,
                "operation_id": "original-operation",
            }
        )
        operations.plane.current.pending.return_value = False
        operations.plane.current.scope.return_value = Scope.model_validate(
            {"id": _SCOPE, "label": "Scope", "state": scope_state}
        )
        operations.fga.bindings.return_value = [scope_object(_SCOPE)]

        assert not await operations._authorized(op)
        operations.fga.check.assert_not_awaited()

    asyncio.run(case())
