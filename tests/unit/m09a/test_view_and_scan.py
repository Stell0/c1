"""M09a D1, D4, D5: security views, the exact binding source, and the catalog cache."""

from __future__ import annotations

import asyncio
import random
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from c1.authorization.audit import Audit
from c1.authorization.fga import FGA, FGAError, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.models import Operation
from c1.authorization.plane import AuthorizationPlane, bound_to_many, use_scan
from c1.authorization.principal import Principal
from c1.authorization.view import SecurityView
from c1.changes import profiles as catalog

P = Principal("c1-dev", "dave", "human")


def _operation(
    index: int, kind: str, target: str, targets: list[str], state: str
) -> dict[str, Any]:
    return {
        "id": f"op-{index}",
        "kind": kind,
        "actor": "user:x",
        "target": target,
        "state": state,
        "targets": targets,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
    }


def _reference_pending(
    operations: list[dict[str, Any]], identifier: str = "", scope: str = "", excluding: str = ""
) -> bool:
    """The pre-M09a `Bindings.pending` loop, kept as the reference."""
    for value in operations:
        operation = Operation.model_validate(value)
        if operation.state != "pending" or operation.id == excluding:
            continue
        if identifier in operation.targets:
            return True
        if (
            scope
            and operation.kind in {"scope_create", "scope_retire", "membership"}
            and operation.target == scope
        ):
            return True
    return False


def test_view_pending_matches_reference_on_generated_journals() -> None:
    rng = random.Random(9)
    kinds = ["scope_create", "scope_retire", "membership", "rescope", "provision", "instance_grant"]
    states = ["pending", "applied", "proposed", "failed"]
    for _ in range(200):
        operations = [
            _operation(
                i,
                rng.choice(kinds),
                rng.choice(["s1", "s2", "r1"]),
                rng.sample(["r1", "r2", "r3"], rng.randint(0, 2)),
                rng.choice(states),
            )
            for i in range(rng.randint(0, 6))
        ]
        view = SecurityView.build("v", [("Operation", op["id"], op) for op in operations])
        for identifier in ("", "r1", "r2", "r3"):
            for scope in ("", "s1", "s2"):
                for excluding in ("", "op-0", "op-1"):
                    assert view.pending(identifier, scope, excluding=excluding) == (
                        _reference_pending(operations, identifier, scope, excluding)
                    )
        assert view.pending_instance_grant == any(
            op["kind"] == "instance_grant" and op["state"] == "pending" for op in operations
        )


def test_view_is_read_only() -> None:
    view = SecurityView.build(
        "v",
        [
            (
                "Binding",
                "r1",
                {"resource_id": "r1", "scope_id": "s", "state": "active", "operation_id": "o"},
            )
        ],
    )
    with pytest.raises(TypeError):
        cast(Any, view.bindings)["r2"] = None


def test_scan_rule_compares_sequential_round_trips() -> None:
    assert not use_scan(5, 3)  # three reads run in one round
    assert not use_scan(1300, 100)  # 15 pages vs 7 rounds
    assert use_scan(1300, 630)  # 15 pages vs 40 rounds
    assert not use_scan(100_000, 630)  # a huge store keeps per-resource reads


class ScanFGA:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls = 0
        self._path = "/stores/s"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        assert "tuple_key" not in kwargs["json"]
        page = self.pages[self.calls]
        self.calls += 1
        return page


def _key(user: str, relation: str, obj: str) -> dict[str, Any]:
    return {"key": {"user": user, "relation": relation, "object": obj}}


def test_scan_keeps_every_bound_to_user_including_unknown_scopes() -> None:
    fga = ScanFGA(
        [
            {
                "tuples": [
                    _key("scope:a", "bound_to", "resource:x"),
                    _key("user:u", "reader", "scope:a"),
                ],
                "continuation_token": "t1",
            },
            {"tuples": [_key("scope:never_created", "bound_to", "resource:x")]},
        ]
    )
    result = asyncio.run(FGA.scan_bindings(cast(FGA, fga)))
    assert result == {"resource:x": ["scope:a", "scope:never_created"]}


@pytest.mark.parametrize("failure", ["repeat", "limit", "invalid"])
def test_scan_failures_raise_without_partial_results(failure: str) -> None:
    pages: list[dict[str, Any]]
    if failure == "repeat":
        pages = [
            {"tuples": [], "continuation_token": "t"},
            {"tuples": [], "continuation_token": "t"},
        ]
        kwargs: dict[str, Any] = {}
    elif failure == "limit":
        pages = [{"tuples": [], "continuation_token": f"t{i}"} for i in range(3)]
        kwargs = {"max_pages": 2}
    else:
        pages = [{"tuples": [{"no_key": True}]}]
        kwargs = {}
    with pytest.raises(FGAError):
        asyncio.run(FGA.scan_bindings(cast(FGA, ScanFGA(pages)), **kwargs))


class SourceFGA:
    """Live tuples served both per object and by whole-store scan."""

    def __init__(self, tuples: dict[str, list[str]]) -> None:
        self.tuples = tuples
        self.reads = 0
        self.scans = 0

    async def bindings(self, obj: str) -> list[str]:
        self.reads += 1
        return list(self.tuples.get(obj, []))

    async def scan_bindings(self) -> dict[str, list[str]]:
        self.scans += 1
        return {k: list(v) for k, v in self.tuples.items()}


def test_both_sources_return_identical_multisets() -> None:
    objects = [resource_object(f"urn:r{i}") for i in range(700)]
    tuples = {obj: [scope_object("s")] for obj in objects[:650]}
    tuples[objects[1]] = [scope_object("s"), scope_object("never_created")]
    per_object = SourceFGA(tuples)
    scanned = SourceFGA(tuples)
    a = asyncio.run(bound_to_many(cast(FGA, per_object), objects, binding_count=100_000))
    b = asyncio.run(bound_to_many(cast(FGA, scanned), objects, binding_count=700))
    assert per_object.reads == 700 and per_object.scans == 0
    assert scanned.scans == 1 and scanned.reads == 0
    assert a == b


class ViewJournal:
    def __init__(self, entries: list[tuple[str, str, dict[str, Any]]], heads: list[str]) -> None:
        self.entries = entries
        self.heads = heads

    async def head(self) -> str:
        return self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]

    async def view(self) -> SecurityView:
        return SecurityView.build("h1", self.entries)


class DecisionFGA(SourceFGA):
    def __init__(self, tuples: dict[str, list[str]], allowed: set[str]) -> None:
        super().__init__(tuples)
        self.allowed = allowed

    async def check(self, _user: str, _relation: str, obj: str) -> bool:
        return obj in self.allowed

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        return [obj in self.allowed for _, _, obj in checks]


def _state_matrix() -> tuple[list[tuple[str, str, dict[str, Any]]], dict[str, list[str]], set[str]]:
    entries: list[tuple[str, str, dict[str, Any]]] = [
        ("Scope", "s", {"id": "s", "label": "S", "state": "active"}),
        ("Scope", "retired", {"id": "retired", "label": "R", "state": "retired"}),
    ]
    tuples: dict[str, list[str]] = {}
    allowed: set[str] = set()
    cases = {
        "ok": ("s", "active", [scope_object("s")], True),
        "denied": ("s", "active", [scope_object("s")], False),
        "inactive": ("s", "revoked", [scope_object("s")], True),
        "retired": ("retired", "active", [scope_object("retired")], True),
        "unknown_scope": ("ghost", "active", [scope_object("ghost")], True),
        "missing_tuple": ("s", "active", [], True),
        "extra_known": ("s", "active", [scope_object("s"), scope_object("retired")], True),
        "extra_unknown": ("s", "active", [scope_object("s"), "scope:never_created"], True),
        "pending": ("s", "active", [scope_object("s")], True),
    }
    for name, (scope, state, live, allow) in cases.items():
        rid = f"urn:{name}"
        entries.append(
            (
                "Binding",
                rid,
                {"resource_id": rid, "scope_id": scope, "state": state, "operation_id": "o"},
            )
        )
        tuples[resource_object(rid)] = live
        if allow:
            allowed.add(resource_object(rid))
    entries.append(
        ("Operation", "op-p", _operation(1, "rescope", "urn:pending", ["urn:pending"], "pending"))
    )
    entries.append(
        (
            "Binding",
            "urn:absent",
            {
                "resource_id": "urn:absent",
                "scope_id": "s",
                "state": "provisioning",
                "operation_id": "o",
            },
        )
    )
    return entries, tuples, allowed


def test_batched_decisions_equal_single_resource_decisions() -> None:
    entries, tuples, allowed = _state_matrix()
    ids = [key for kind, key, _ in entries if kind == "Binding"] + ["urn:nothing"]

    async def run(batch_size: int) -> dict[str, Any]:
        journal = ViewJournal(entries, ["h1"])
        fga = DecisionFGA(tuples, allowed)
        plane = AuthorizationPlane(cast(Journal, journal), cast(FGA, fga), "unit", Audit())
        result: dict[str, Any] = {}
        for start in range(0, len(ids), batch_size):
            result.update(await plane.check_many(P, ids[start : start + batch_size], "can_read"))
        return result

    single = asyncio.run(run(1))
    batched = asyncio.run(run(len(ids)))
    assert single == batched
    reasons = {key: value.reason for key, value in single.items()}
    assert reasons == {
        "urn:ok": "allowed",
        "urn:denied": "permission_denied",
        "urn:inactive": "inactive_binding",
        "urn:retired": "unresolved_scope",
        "urn:unknown_scope": "unresolved_scope",
        "urn:missing_tuple": "inconsistent_binding",
        "urn:extra_known": "inconsistent_binding",
        "urn:extra_unknown": "inconsistent_binding",
        "urn:pending": "pending_security_operation",
        "urn:absent": "inactive_binding",
        "urn:nothing": "inactive_binding",
    }


def test_head_change_or_backend_failure_denies_the_whole_batch() -> None:
    entries, tuples, allowed = _state_matrix()

    async def run(heads: list[str], fail: bool) -> set[str]:
        fga = DecisionFGA(tuples, allowed)
        if fail:

            async def broken(_obj: str) -> list[str]:
                raise RuntimeError("down")

            fga.bindings = broken  # type: ignore[method-assign,assignment]
        plane = AuthorizationPlane(
            cast(Journal, ViewJournal(entries, heads)), cast(FGA, fga), "unit", Audit()
        )
        decisions = await plane.check_many(P, ["urn:ok", "urn:denied"], "can_read")
        return {d.reason for d in decisions.values() if not d.allowed} | {
            d.reason for d in decisions.values() if d.allowed
        }

    assert asyncio.run(run(["h1", "h2"], False)) == {"security_revision_changed"}
    assert asyncio.run(run(["h1"], True)) == {"security_unavailable"}
    assert asyncio.run(run(["h0", "h1"], False)) == {"security_revision_changed"}


def test_catalog_cache_reparses_only_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "profiles"
    shutil.copytree(Path(catalog.__file__).resolve().parents[3] / "profiles", root)
    monkeypatch.setattr(catalog, "_catalog_root", lambda: root / "available")
    catalog._PARSED.clear()
    first, name = catalog.load_candidate("topics")
    again, _ = catalog.load_candidate("topics")
    assert len(catalog._PARSED) == 1 and name == "topics"
    assert first is not again  # private copies; the shared parse is never handed out
    manifest = root / "available/topics/profile.json"
    manifest.write_text(manifest.read_text().replace('"version": "1.0.0"', '"version": "1.0.1"'))
    _, _ = catalog.load_candidate("topics")
    assert len(catalog._PARSED) == 2
