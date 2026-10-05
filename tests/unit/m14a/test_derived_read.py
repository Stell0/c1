"""M14a (ADR-0025): derived read decisions equal per-resource can_read checks."""

from __future__ import annotations

import asyncio
import copy
import random
from typing import Any, cast

import pytest

from c1.authorization.audit import Audit
from c1.authorization.fga import (
    FGA,
    model_definition,
    read_relation_is_derivable,
    resource_object,
    scope_object,
)
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.query.plan import AuthorizedSelection, QueryPlanError
from tests.unit.m05.test_plan import _PRINCIPAL, FakeJournal


class ModelFGA:
    """Evaluates the pinned model from tuples: can_read = reader from bound_to."""

    def __init__(self, verified: bool) -> None:
        self.read_model_verified = verified
        self.bound: dict[str, list[str]] = {}  # resource object -> scope objects
        self.readers: dict[str, set[str]] = {}  # scope object -> users and group#member
        self.members: dict[str, set[str]] = {}  # group -> users
        self.checks = 0

    def _reader(self, user: str, scope: str) -> bool:
        direct = self.readers.get(scope, set())
        return user in direct or any(
            entry.endswith("#member") and user in self.members.get(entry[:-7], set())
            for entry in direct
        )

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        assert (relation, type) == ("reader", "scope")
        return sorted(scope for scope in self.readers if self._reader(user, scope))

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        self.checks += len(checks)
        results = []
        for user, relation, obj in checks:
            assert relation == "can_read"
            results.append(any(self._reader(user, s) for s in self.bound.get(obj, [])))
        return results

    async def check(self, user: str, relation: str, obj: str) -> bool:
        return (await self.batch_check([(user, relation, obj)]))[0]

    async def bindings(self, resource: str) -> list[str]:
        return list(self.bound.get(resource, []))

    async def scan_bindings(self) -> dict[str, list[str]]:
        return {obj: list(users) for obj, users in self.bound.items() if users}


def _planner(journal: FakeJournal, fga: ModelFGA) -> AuthorizedSelection:
    typed_journal = cast(Journal, journal)
    plane = AuthorizationPlane(typed_journal, cast(FGA, fga), "test", Audit())
    return AuthorizedSelection(typed_journal, cast(FGA, fga), plane)


def _world(seed: int) -> tuple[FakeJournal, ModelFGA]:
    rng = random.Random(seed)
    journal, fga = FakeJournal(), ModelFGA(verified=False)
    scopes = [f"s{n}" for n in range(5)]
    journal.scopes = [{"id": s, "label": s, "state": "active"} for s in scopes]
    fga.members["group:team"] = {_PRINCIPAL.id} if rng.random() < 0.5 else set()
    for scope in scopes:
        entries: set[str] = set()
        roll = rng.random()
        if roll < 0.3:
            entries.add(_PRINCIPAL.id)
        elif roll < 0.5:
            entries.add("group:team#member")
        elif roll < 0.6:
            entries.add("user:someone-else")
        fga.readers[scope_object(scope)] = entries
    for n in range(40):
        identifier = f"urn:test:r{n}"
        scope = rng.choice(scopes)
        journal.add(identifier, scope)
        live = [scope_object(scope)]
        roll = rng.random()
        if roll < 0.1:
            live = []  # publication not confirmed
        elif roll < 0.2:
            live = [scope_object(rng.choice(scopes))]  # diverged binding
        elif roll < 0.25:
            live = [scope_object(scope), scope_object(rng.choice(scopes))]  # extra tuple
        fga.bound[resource_object(identifier)] = live
    return journal, fga


@pytest.mark.parametrize("seed", range(25))
def test_derived_decisions_equal_per_resource_checks(seed: int) -> None:
    async def run() -> None:
        journal, legacy = _world(seed)
        derived = copy.deepcopy(legacy)
        derived.read_model_verified = True
        old = await _planner(journal, legacy).build(_PRINCIPAL)
        new = await _planner(journal, derived).build(_PRINCIPAL)
        assert new.authorized_ids == old.authorized_ids
        assert derived.checks == 0
        # Revocation between build and finalize is seen by both paths.
        for fga in (legacy, derived):
            for scope in list(fga.readers):
                fga.readers[scope].discard(_PRINCIPAL.id)
            fga.members["group:team"] = set()
        for fga, plan in ((legacy, old), (derived, new)):
            planner = _planner(journal, fga)
            if plan.authorized_ids:
                with pytest.raises(QueryPlanError):
                    await planner.finalize(_PRINCIPAL, plan)
            else:
                await planner.finalize(_PRINCIPAL, plan)

    asyncio.run(run())


def test_packaged_model_has_the_derivable_read_shape() -> None:
    assert read_relation_is_derivable(model_definition())


def test_served_camel_case_model_has_the_derivable_read_shape() -> None:
    """The shape OpenFGA 1.21.0 returns from GET authorization-models/{id}."""
    served = copy.deepcopy(model_definition())
    for item in served["type_definitions"]:
        if item["type"] == "resource":
            item["relations"]["can_read"] = {
                "tupleToUserset": {
                    "tupleset": {"object": "", "relation": "bound_to"},
                    "computedUserset": {"object": "", "relation": "reader"},
                }
            }
    assert read_relation_is_derivable(served)


def _mutate(model: dict[str, Any], kind: str) -> dict[str, Any]:
    changed = copy.deepcopy(model)
    types = {t["type"]: t for t in changed["type_definitions"]}
    if kind == "union":
        rel = types["resource"]["relations"]["can_read"]
        types["resource"]["relations"]["can_read"] = {
            "union": {"child": [rel, {"computed_userset": {"relation": "bound_to"}}]}
        }
    elif kind == "tupleset":
        types["resource"]["relations"]["can_read"]["tuple_to_userset"]["tupleset"]["relation"] = (
            "inherits_from"
        )
    elif kind == "computed":
        types["resource"]["relations"]["can_read"]["tuple_to_userset"]["computed_userset"][
            "relation"
        ] = "contributor"
    elif kind == "scope_reader":
        types["scope"]["relations"]["reader"] = {
            "union": {"child": [{"this": {}}, {"computed_userset": {"relation": "reviewer"}}]}
        }
    elif kind == "missing":
        del types["resource"]["relations"]["can_read"]
    return changed


@pytest.mark.parametrize("kind", ["union", "tupleset", "computed", "scope_reader", "missing"])
def test_any_other_model_shape_disables_derivation(kind: str) -> None:
    assert not read_relation_is_derivable(_mutate(model_definition(), kind))
    assert not read_relation_is_derivable({})
