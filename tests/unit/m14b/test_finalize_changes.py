"""M14b D3 (ADR-0026): finalize reuses the plan only when the store is unchanged."""

from __future__ import annotations

import asyncio

import pytest

from c1.authorization.fga import resource_object, scope_object
from c1.query.plan import QueryPlanError
from tests.unit.m05.test_plan import _PRINCIPAL, FakeJournal
from tests.unit.m14a.test_derived_read import ModelFGA, _planner


class LoggedFGA(ModelFGA):
    """The model FGA plus an append-only change log, like OpenFGA's."""

    def __init__(self) -> None:
        super().__init__(verified=True)
        self.log: list[str] = []
        self.reads = 0
        self.fail_log = False

    def change(self, what: str) -> None:
        self.log.append(what)

    async def read_changes(self, token: str) -> tuple[str, bool]:
        if self.fail_log:
            raise RuntimeError("change log unavailable")
        start = int(token) if token else 0
        return str(len(self.log)), len(self.log) > start

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        self.reads += 1
        return await super().list_objects(user, relation, type)

    async def scan_bindings(self) -> dict[str, list[str]]:
        self.reads += 1
        return {obj: list(users) for obj, users in self.bound.items() if users}

    async def bindings(self, resource: str) -> list[str]:
        self.reads += 1
        return await super().bindings(resource)


def _world() -> tuple[FakeJournal, LoggedFGA]:
    journal, fga = FakeJournal(), LoggedFGA()
    journal.scopes = [{"id": s, "label": s, "state": "active"} for s in ("a", "b")]
    fga.readers = {scope_object("a"): {"group:team#member"}, scope_object("b"): set()}
    fga.members["group:team"] = {_PRINCIPAL.id}
    for n in range(5):
        identifier = f"urn:test:r{n}"
        journal.add(identifier, "a")
        fga.bound[resource_object(identifier)] = [scope_object("a")]
    return journal, fga


def test_unchanged_store_reuses_the_plan_without_openfga_reads() -> None:
    async def run() -> None:
        journal, fga = _world()
        planner = _planner(journal, fga)
        plan = await planner.build(_PRINCIPAL)
        assert len(plan.authorized_ids) == 5 and plan.change_token is not None
        reads = fga.reads
        await planner.finalize(_PRINCIPAL, plan)
        assert fga.reads == reads

    asyncio.run(run())


@pytest.mark.parametrize("change", ["revoke_membership", "rescope", "remove_reader"])
def test_any_change_forces_fresh_reads_and_is_enforced(change: str) -> None:
    async def run() -> None:
        journal, fga = _world()
        planner = _planner(journal, fga)
        plan = await planner.build(_PRINCIPAL)
        if change == "revoke_membership":
            fga.members["group:team"] = set()
        elif change == "rescope":
            fga.bound[resource_object("urn:test:r0")] = [scope_object("b")]
        else:
            fga.readers[scope_object("a")] = set()
        fga.change(change)
        reads = fga.reads
        with pytest.raises(QueryPlanError):
            await planner.finalize(_PRINCIPAL, plan)
        assert fga.reads > reads

    asyncio.run(run())


def test_unrelated_change_still_takes_the_fresh_path_and_passes() -> None:
    async def run() -> None:
        journal, fga = _world()
        planner = _planner(journal, fga)
        plan = await planner.build(_PRINCIPAL)
        fga.change("unrelated tuple")
        reads = fga.reads
        await planner.finalize(_PRINCIPAL, plan)
        assert fga.reads > reads

    asyncio.run(run())


def test_change_log_errors_fall_back_to_fresh_reads() -> None:
    async def run() -> None:
        journal, fga = _world()
        planner = _planner(journal, fga)
        plan = await planner.build(_PRINCIPAL)
        fga.fail_log = True
        fga.members["group:team"] = set()  # a change the broken log cannot report
        with pytest.raises(QueryPlanError):
            await planner.finalize(_PRINCIPAL, plan)

    asyncio.run(run())


def test_unverified_model_never_uses_the_shortcut() -> None:
    async def run() -> None:
        journal, fga = _world()
        fga.read_model_verified = False
        plan = await _planner(journal, fga).build(_PRINCIPAL)
        assert plan.change_token is None

    asyncio.run(run())
