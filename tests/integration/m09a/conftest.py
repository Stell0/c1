"""M09a real-service helpers: a provisioned state matrix and the legacy reference."""

from __future__ import annotations

import os
from typing import Any

import pytest

from c1.authorization.fga import resource_object
from c1.authorization.models import Binding, Decision, Operation, Scope
from c1.authorization.principal import Principal
from tests.integration.m03.conftest import LiveCase, entity_record
from tests.integration.software import fresh_tokens


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m09a/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M09a real services require C1_STACK=1"))


async def legacy_decision(case: LiveCase, p: Principal, identifier: str) -> Decision:
    """The pre-M09a single-resource check (ADR-0009), kept as the reference."""
    try:
        before = await case.journal.head()
        value = await case.journal.get("Binding", identifier)
        binding = Binding.model_validate(value) if value is not None else None
        if binding is None or binding.state != "active":
            return Decision(False, "inactive_binding")
        raw_scope = await case.journal.get("Scope", binding.scope_id)
        scope = Scope.model_validate(raw_scope) if raw_scope is not None else None
        if scope is None or scope.state != "active":
            return Decision(False, "unresolved_scope")
        for raw in await case.journal.list("Operation"):
            operation = Operation.model_validate(raw)
            if operation.state != "pending":
                continue
            if identifier in operation.targets or (
                operation.kind in {"scope_create", "scope_retire", "membership"}
                and operation.target == binding.scope_id
            ):
                return Decision(False, "pending_security_operation")
        obj = resource_object(identifier)
        if await case.fga.bindings(obj) != ["scope:" + binding.scope_id]:
            return Decision(False, "inconsistent_binding")
        allowed = await case.fga.check(p.id, "can_read", obj)
        if before != await case.journal.head():
            return Decision(False, "security_revision_changed")
        return Decision(allowed, "allowed" if allowed else "permission_denied")
    except Exception:
        return Decision(False, "security_unavailable")


async def provision_matrix(case: LiveCase, count: int) -> tuple[str, str, dict[str, Any]]:
    """`count` readable resources in one scope plus one resource per fault kind."""
    fresh_tokens(case)  # provisioning on a slow host outlives one access token
    shared = await case.scope("M09a shared")
    other = await case.scope("M09a other")
    await case.grant(shared, "alice", "reader")
    ids: dict[str, Any] = {"plain": []}
    for index in range(count):
        record = entity_record(label=f"M09a {index}")
        await case.provision(record, shared)
        ids["plain"].append(record.id)
    for kind in ("missing", "extra_known", "extra_unknown", "revoked", "pending", "denied"):
        record = entity_record(label=f"M09a {kind}")
        await case.provision(record, other if kind == "denied" else shared)
        ids[kind] = record.id
    return shared, other, ids
