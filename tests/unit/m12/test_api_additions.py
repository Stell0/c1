"""M12 D7: the scope and security-operation listings show only what the caller can act on."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from c1.api import create_app
from c1.authorization.errors import SecurityError
from c1.authorization.fga import scope_object
from c1.authorization.models import Decision, Operation, Scope
from c1.authorization.operations import SecurityOperations
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.model.profiles import ProfileRegistry
from c1.runtime import Runtime

ALICE = Principal("dev", "alice", "human")
CAROL = Principal("dev", "carol", "human")
ERIN = Principal("dev", "erin", "human")
FRANK = Principal("dev", "frank", "human")
S_SHARED = "sw-shared"
S_DOCS = "sw-docs"
S_DRAFTS = "drafts-bob"
S_RETIRED = "old"


@dataclass
class _View:
    version: str
    scopes: dict[str, Scope]


@dataclass
class _Journal:
    operations: list[dict[str, Any]] = field(default_factory=list)
    heads: list[str] = field(default_factory=lambda: ["h1"])

    async def head(self) -> str:
        return self.heads[0] if len(self.heads) == 1 else self.heads.pop(0)

    async def view(self) -> _View:
        return _View(
            "h1",
            {
                S_SHARED: Scope(id=S_SHARED, label="Shared"),
                S_DOCS: Scope(id=S_DOCS, label="Docs"),
                S_DRAFTS: Scope(id=S_DRAFTS, label="Bob drafts", kind="drafting"),
                S_RETIRED: Scope(id=S_RETIRED, label="Old", state="retired"),
            },
        )

    async def list(self, kind: str) -> list[dict[str, Any]]:
        assert kind == "Operation"
        return self.operations

    async def get(self, kind: str, identifier: str) -> dict[str, Any] | None:
        assert kind == "Operation"
        return next((op for op in self.operations if op["id"] == identifier), None)


GRANTS = {
    (ALICE.id, "reader", S_SHARED),
    (ALICE.id, "reader", S_DOCS),
    (CAROL.id, "access_admin", S_DRAFTS),
    (CAROL.id, "access_admin", S_DOCS),
    (FRANK.id, "access_admin", S_DOCS),
    (ERIN.id, "access_admin", S_SHARED),
    (ERIN.id, "access_admin", S_RETIRED),
}


class _FGA:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str]] = []

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        if self.fail:
            raise OSError("unavailable")
        self.calls.extend(checks)
        return [(u, r, o.removeprefix("scope:")) in GRANTS for u, r, o in checks]


class _Plane:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def check_scope(self, p: Principal, op: str, scope_id: str) -> Decision:
        if self.fail:
            return Decision(False, "security_unavailable")
        allowed = (p.id, op, scope_id) in GRANTS
        return Decision(allowed, "allowed" if allowed else "permission_denied")

    async def check_instance(self, p: Principal, op: str) -> Decision:
        return Decision(False, "permission_denied")


def _operations(journal: _Journal, *, fga: _FGA | None = None, plane: _Plane | None = None) -> Any:
    ops = object.__new__(SecurityOperations)
    ops.journal = cast(Any, journal)
    ops.fga = cast(Any, fga or _FGA())
    ops.plane = cast(Any, plane or _Plane())
    return ops


def _op(identifier: str, actor: str, created: str, **kwargs: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        id=identifier,
        kind="rescope",
        actor=actor,
        target="urn:c1:instance:test:doc/draft",
        from_scope=S_DRAFTS,
        to_scope=S_DOCS,
        state="proposed",
        created=created,
        updated=created,
        payload={"lineage": {"scopes": [S_SHARED]}},
    )
    values.update(kwargs)
    return Operation(**values).model_dump(mode="json")


def test_my_scopes_lists_only_the_callers_own_active_roles() -> None:
    async def run() -> None:
        fga = _FGA()
        ops = _operations(_Journal(), fga=fga)
        assert await ops.my_scopes(ALICE) == [
            {"id": S_DOCS, "label": "Docs", "kind": "standard", "roles": ["reader"]},
            {"id": S_SHARED, "label": "Shared", "kind": "standard", "roles": ["reader"]},
        ]
        # The retired scope is never checked or listed, even for its admin.
        assert all(obj != scope_object(S_RETIRED) for _u, _r, obj in fga.calls)
        assert await ops.my_scopes(ERIN) == [
            {"id": S_SHARED, "label": "Shared", "kind": "standard", "roles": ["access_admin"]}
        ]
        assert await ops.my_scopes(Principal("dev", "nobody", "human")) == []

    asyncio.run(run())


def test_my_scopes_fails_closed() -> None:
    async def run() -> None:
        with pytest.raises(SecurityError) as error:
            await _operations(_Journal(), fga=_FGA(fail=True)).my_scopes(ALICE)
        assert error.value.status == 503
        # A security revision change during the listing is not answered either.
        with pytest.raises(SecurityError) as error:
            await _operations(_Journal(heads=["h1", "h2"])).my_scopes(ALICE)
        assert error.value.status == 503

    asyncio.run(run())


def test_operation_listing_matches_read_rule() -> None:
    async def run() -> None:
        journal = _Journal(
            operations=[
                _op("op-1", CAROL.id, "2026-10-01T00:00:00+00:00"),
                _op(
                    "op-2",
                    CAROL.id,
                    "2026-10-02T00:00:00+00:00",
                    kind="membership",
                    target=S_DOCS,
                    from_scope=None,
                    to_scope=None,
                    payload={},
                ),
                _op(
                    "op-3",
                    ALICE.id,
                    "2026-10-03T00:00:00+00:00",
                    kind="changeset_apply",
                    from_scope=None,
                    to_scope=None,
                    payload={},
                ),
            ]
        )
        ops = _operations(journal)
        carol = await ops.list_operations(CAROL)
        assert [o["id"] for o in carol["security_operations"]] == ["op-2", "op-1"]
        assert all("payload" not in o for o in carol["security_operations"])
        # Frank administers the destination; Erin only a lineage scope (M11 D7).
        assert [o["id"] for o in (await ops.list_operations(FRANK))["security_operations"]] == [
            "op-1"
        ]
        assert [o["id"] for o in (await ops.list_operations(ERIN))["security_operations"]] == [
            "op-1"
        ]
        assert (await ops.get_operation(ERIN, "op-1"))["id"] == "op-1"
        # Alice administers nothing and proposed only an internal ChangeSet apply.
        assert await ops.list_operations(ALICE) == {"security_operations": [], "truncated": False}
        with pytest.raises(SecurityError) as error:
            await ops.get_operation(ALICE, "op-1")
        assert error.value.status == 403
        bounded = await ops.list_operations(CAROL, limit=1)
        assert [o["id"] for o in bounded["security_operations"]] == ["op-2"]
        assert bounded["truncated"] is True

    asyncio.run(run())


def test_operation_listing_fails_closed_on_authorization_outage() -> None:
    async def run() -> None:
        journal = _Journal(operations=[_op("op-1", CAROL.id, "2026-10-01T00:00:00+00:00")])
        with pytest.raises(SecurityError) as error:
            await _operations(journal, plane=_Plane(fail=True)).list_operations(FRANK)
        assert error.value.status == 503

    asyncio.run(run())


class _Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = ProfileRegistry()
        self.events: list[str] = []
        self.audit = self
        self.tokens = self

    def emit(self, principal: str = "", operation: str = "", *_a: Any, **_k: Any) -> None:
        self.events.append(operation)

    async def authenticate(self, token: str) -> Principal:
        return ALICE

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_schema_route_describes_installed_profiles_without_instance_data(tmp_path: Path) -> None:
    settings = Settings(
        instance_id="c1test",
        instance_base="urn:c1:instance:test:",
        issuer="http://127.0.0.1:18090/realms/test",
        issuer_alias="dev",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token="test-secret",
        fga_store="test-store",
        fga_model="test-model",
        terminus_url="http://127.0.0.1:16363",
        terminus_password="test-secret",  # pragma: allowlist secret - local fake credential
        organization="admin",
        knowledge_database="knowledge_test",
        workflow_database="workflow_test",
        lock_path=tmp_path / "lock",
    )
    fake = _Runtime(settings)

    async def run() -> None:
        app = create_app(settings, runtime=cast(Runtime, fake))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"Authorization": "Bearer good"}
                response = await client.get("/v1/schema", headers=headers)
                assert response.status_code == 200
                body = response.json()
                assert set(body) == {"instance", "profiles", "available_profiles"}
                assert [p["name"] for p in body["profiles"]] == ["core"]
                entity = next(
                    c for c in body["profiles"][0]["classes"] if c["iri"] == "urn:c1:ns:core#Entity"
                )
                lifecycle = next(
                    p for p in entity["properties"] if p["iri"] == "urn:c1:ns:core#lifecycle"
                )
                assert lifecycle["enum"] == ["active", "retracted", "superseded"]
                assert "example-vehicle" in body["available_profiles"]
                # Definitions only: no instance, count or example fields anywhere.
                for profile in body["profiles"]:
                    assert set(profile) == {"name", "version", "classes"}
                    for item in profile["classes"]:
                        assert set(item) == {"iri", "kind", "properties"}
                assert (
                    await client.get("/v1/schema?revision=x", headers=headers)
                ).status_code == 400
                assert (await client.get("/v1/schema")).status_code == 401
        assert "schema_read" in fake.events

    asyncio.run(run())
