"""Authorized selection must precede every query observation."""

from __future__ import annotations

import asyncio
import builtins
from typing import Any, cast

import pytest

from c1.authorization.audit import Audit
from c1.authorization.fga import FGA, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.query.plan import AuthorizedSelection, QueryPlanError

_PRINCIPAL = Principal("c1-dev", "alice", "human")


class FakeJournal:
    head_value = "workflow:1"

    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = [
            {"id": "shared", "label": "Shared", "state": "active"},
            {"id": "private", "label": "Private", "state": "active"},
        ]
        self.bindings: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        self.list_calls = 0

    def add(self, identifier: str, scope: str = "shared", state: str = "active") -> None:
        self.bindings.append(
            {
                "resource_id": identifier,
                "scope_id": scope,
                "state": state,
                "operation_id": "op-1",
            }
        )

    async def head(self) -> str:
        return self.head_value

    async def list(self, kind: str) -> list[dict[str, Any]]:
        self.list_calls += 1
        return {"Scope": self.scopes, "Binding": self.bindings, "Operation": self.operations}[kind]

    async def list_many(self, kinds: set[str]) -> dict[str, builtins.list[dict[str, Any]]]:
        self.list_calls += 1
        rows = {
            "Scope": self.scopes,
            "Binding": self.bindings,
            "Operation": self.operations,
            "ChangeSet": [],
        }
        return {kind: rows[kind] for kind in kinds}

    async def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return next(
            (row for row in await self.list(kind) if row.get("id", row.get("resource_id")) == key),
            None,
        )


class FakeFGA:
    def __init__(self) -> None:
        self.scopes = [scope_object("shared")]
        self.allowed: set[str] = set()
        self.live_bindings: dict[str, list[str]] = {}
        self.checked: list[str] = []
        self.fail = False
        self.fail_binding = False

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        assert (user, relation, type) == (_PRINCIPAL.id, "reader", "scope")
        if self.fail:
            raise RuntimeError("service down")
        return self.scopes

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        self.checked.extend(item[2] for item in checks)
        return [item[2] in self.allowed for item in checks]

    async def bindings(self, resource: str) -> list[str]:
        if self.fail_binding:
            raise RuntimeError("service down")
        return self.live_bindings.get(resource, [])


def _planner(journal: FakeJournal, fga: FakeFGA) -> AuthorizedSelection:
    typed_journal = cast(Journal, journal)
    typed_fga = cast(FGA, fga)
    plane = AuthorizationPlane(typed_journal, typed_fga, "test", Audit())
    return AuthorizedSelection(typed_journal, typed_fga, plane)


def _allow(fga: FakeFGA, identifier: str, scope: str = "shared") -> None:
    obj = resource_object(identifier)
    fga.allowed.add(obj)
    fga.live_bindings[obj] = [scope_object(scope)]


def test_all_provisional_candidates_checked_before_selection() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        for identifier in ("urn:test:a", "urn:test:b", "urn:test:c"):
            journal.add(identifier)
            _allow(fga, identifier)
        fga.allowed.remove(resource_object("urn:test:b"))
        journal.add("urn:test:hidden", "private")
        journal.add("urn:test:pending")
        journal.operations.append(
            {
                "id": "pending-1",
                "kind": "rescope",
                "actor": "user:c1-dev.admin",
                "target": "urn:test:pending",
                "state": "pending",
                "targets": ["urn:test:pending"],
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
            }
        )
        plan = await _planner(journal, fga).build(_PRINCIPAL)
        assert plan.authorized_ids == ("urn:test:a", "urn:test:c")
        assert dict(plan.scope_by_id) == {
            "urn:test:a": "shared",
            "urn:test:c": "shared",
        }
        assert set(fga.checked) == {
            resource_object("urn:test:a"),
            resource_object("urn:test:b"),
            resource_object("urn:test:c"),
        }
        assert resource_object("urn:test:hidden") not in fga.checked
        assert resource_object("urn:test:pending") not in fga.checked

    asyncio.run(run())


def test_live_binding_mismatch_excludes_inconsistent_candidate() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        journal.add("urn:test:a")
        journal.add("urn:test:b")
        _allow(fga, "urn:test:a")
        _allow(fga, "urn:test:b", "private")
        plan = await _planner(journal, fga).build(_PRINCIPAL)
        assert plan.authorized_ids == ("urn:test:a",)
        assert set(fga.checked) == {resource_object("urn:test:a"), resource_object("urn:test:b")}

    asyncio.run(run())


def test_head_change_invalidates_cached_index_and_plan() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        journal.add("urn:test:a")
        _allow(fga, "urn:test:a")
        planner = _planner(journal, fga)
        await planner.build(_PRINCIPAL)
        initial_lists = journal.list_calls
        initial_checks = len(fga.checked)
        await planner.build(_PRINCIPAL)
        assert journal.list_calls == initial_lists  # exact-head projection reused
        assert len(fga.checked) == initial_checks + 1  # fresh FGA decision
        journal.head_value = "workflow:2"
        journal.add("urn:test:b")
        _allow(fga, "urn:test:b")
        plan = await planner.build(_PRINCIPAL)
        assert journal.list_calls == initial_lists + 1
        assert plan.workflow_head == "workflow:2"
        assert plan.authorized_ids == ("urn:test:a", "urn:test:b")

        class FlippingFGA(FakeFGA):
            async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
                journal.head_value = "workflow:3"
                return await super().batch_check(checks)

        changed_fga = FlippingFGA()
        changed_fga.allowed = fga.allowed
        changed_fga.live_bindings = fga.live_bindings
        with pytest.raises(QueryPlanError) as error:
            await _planner(journal, changed_fga).build(_PRINCIPAL)
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")

    asyncio.run(run())


def test_caps_and_service_error_fail_closed() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        fga.scopes = [scope_object(f"s{i}") for i in range(500)]
        with pytest.raises(QueryPlanError) as scope_error:
            await _planner(journal, fga).build(_PRINCIPAL)
        assert (scope_error.value.status, scope_error.value.code) == (422, "C1-QY-050")
        fga.scopes = [scope_object("shared")]
        for i in range(5001):
            journal.add(f"urn:test:{i}")
        with pytest.raises(QueryPlanError) as candidate_error:
            await _planner(journal, fga).build(_PRINCIPAL)
        assert (candidate_error.value.status, candidate_error.value.code) == (422, "C1-QY-052")
        assert fga.checked == []
        fga.fail = True
        with pytest.raises(QueryPlanError) as service_error:
            await _planner(journal, fga).build(_PRINCIPAL)
        assert (service_error.value.status, service_error.value.code) == (503, "C1-QY-054")

    asyncio.run(run())


def test_deadline_failure_never_returns_partial_plan() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        journal.add("urn:test:a")
        _allow(fga, "urn:test:a")
        with pytest.raises(QueryPlanError) as error:
            await _planner(journal, fga).build(_PRINCIPAL, deadline=0)
        assert (error.value.status, error.value.code) == (503, "C1-QY-053")

    asyncio.run(run())


def test_finalization_rejects_revocation_after_content_selection() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        journal.add("urn:test:a")
        _allow(fga, "urn:test:a")
        planner = _planner(journal, fga)
        plan = await planner.build(_PRINCIPAL)
        fga.allowed.remove(resource_object("urn:test:a"))
        with pytest.raises(QueryPlanError) as error:
            await planner.finalize(_PRINCIPAL, plan)
        assert (error.value.status, error.value.code) == (409, "C1-QY-051")

    asyncio.run(run())


def test_plane_service_failure_aborts_instead_of_returning_partial_results() -> None:
    async def run() -> None:
        journal, fga = FakeJournal(), FakeFGA()
        journal.add("urn:test:a")
        _allow(fga, "urn:test:a")
        fga.fail_binding = True
        with pytest.raises(QueryPlanError) as error:
            await _planner(journal, fga).build(_PRINCIPAL)
        assert (error.value.status, error.value.code) == (503, "C1-QY-054")

    asyncio.run(run())
