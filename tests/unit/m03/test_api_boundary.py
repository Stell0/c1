"""The HTTP boundary authenticates first and cannot select another authority."""

import asyncio
from pathlib import Path
from typing import Any, cast

import httpx

from c1.api import create_app
from c1.authorization.models import Decision
from c1.authorization.principal import Principal
from c1.authorization.tokens import AuthenticationError
from c1.config import Settings
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.runtime import Runtime

_PRINCIPAL = Principal("dev", "alice", "human")
_OTHER = Principal("dev", "bob", "human")
_SCOPE = "urn:c1:probe:scope/admin"
_RESOURCE = "urn:c1:probe:entity/one"


class _Tokens:
    async def authenticate(self, token: str) -> Principal:
        if token == "good":
            return _PRINCIPAL
        raise AuthenticationError()


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def emit(
        self,
        principal: str,
        operation: str,
        target: str = "",
        outcome: str = "denied",
        reason: str = "",
        correlation_id: str = "",
    ) -> None:
        self.events.append(
            dict(
                principal=principal,
                operation=operation,
                target=target,
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
            )
        )


class _Plane:
    async def check_scope(self, principal: Principal, op: str, scope_id: str) -> Decision:
        return Decision(
            principal == _PRINCIPAL and op == "access_admin" and scope_id == _SCOPE, "test"
        )

    async def check_instance(self, principal: Principal, op: str) -> Decision:
        return Decision(principal == _PRINCIPAL and op == "operator", "test")


class _Journal:
    async def list(self, kind: str) -> list[dict[str, Any]]:
        assert kind == "Scope"
        return [
            {"id": _SCOPE, "label": "admin", "state": "active"},
            {"id": "urn:c1:probe:scope/hidden", "label": "hidden", "state": "active"},
        ]


class _Operations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create_scope(
        self, _p: Principal, label: str, id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("create_scope", label))
        return {"id": id or _SCOPE, "label": label, "state": "active"}

    async def membership(
        self, _p: Principal, scope: str, _member: str, role: str, *, grant: bool = True
    ) -> dict[str, Any]:
        self.calls.append(("membership", role))
        return {"scope": scope, "role": role, "grant": grant}

    async def provision(
        self,
        _p: Principal,
        record: NodeRecord,
        scope_id: str | None = None,
        inherited_from: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("provision", record.id))
        return {"resource_id": record.id, "revision": "branch:test", "operation_id": "op:test"}

    async def revise_probe(
        self, _p: Principal, resource_id: str, _record: NodeRecord
    ) -> dict[str, Any]:
        self.calls.append(("revise_probe", resource_id))
        return {"resource_id": resource_id, "revision": "branch:next"}

    async def recover(self) -> dict[str, Any]:
        self.calls.append(("recover", ""))
        return {"status": "recovered"}


class _Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tokens = _Tokens()
        self.audit = _Audit()
        self.plane = _Plane()
        self.journal = _Journal()
        self.operations = _Operations()
        self.ready_value = True
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def ready(self) -> bool:
        return self.ready_value

    async def read(
        self, _principal: Principal, resource_id: str, revision: str | None = None
    ) -> NodeRecord | None:
        if resource_id != _RESOURCE or revision == "hidden":
            return None
        return _record()


def _settings(tmp_path: Path, *, probe: bool) -> Settings:
    return Settings(
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
        terminus_password="test-secret",
        organization="admin",
        knowledge_database="knowledge_test",
        workflow_database="workflow_test",
        lock_path=tmp_path / "lock",
        enable_probe_routes=probe,
    )


def _record() -> NodeRecord:
    return NodeRecord(
        id=_RESOURCE,
        types=["urn:c1:ns:core#Entity"],
        properties={
            "http://www.w3.org/2004/02/skos/core#prefLabel": [
                LiteralValue(lexical="Synthetic", datatype=XSD_STRING)
            ],
            "urn:c1:ns:core#lifecycle": [LiteralValue(lexical="active", datatype=XSD_STRING)],
        },
    )


def test_authentication_readiness_and_delegation(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path, probe=False)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                assert (await client.get("/v1/readyz")).json() == {"ready": True}
                assert (await client.get("/v1/readyz?database=other")).status_code == 400
                assert (
                    await client.get("/v1/readyz", headers={"X-C1-Store": "other"})
                ).status_code == 400
                assert (await client.post("/v1/readyz")).status_code == 401
                fake.ready_value = False
                unavailable = await client.get("/v1/readyz")
                assert unavailable.status_code == 503
                assert unavailable.json()["type"] == "about:blank#unavailable"
                assert (await client.get("/v1/whoami")).status_code == 401
                assert (
                    await client.get("/v1/whoami", headers={"Authorization": "Bearer bad"})
                ).status_code == 401
                headers = {"Authorization": "Bearer good", "X-On-Behalf-Of": _OTHER.id}
                response = await client.request(
                    "GET", "/v1/whoami", headers=headers, json={"on_behalf_of": _OTHER.id}
                )
                assert response.status_code == 200
                assert response.json() == {
                    "issuer_alias": "dev",
                    "subject": "alice",
                    "kind": "human",
                }
                assert [
                    e["reason"]
                    for e in fake.audit.events
                    if e["operation"] == "attempted_delegation"
                ] == ["client_header", "client_body"]
                assert (await client.get("/openapi.json", headers=headers)).status_code == 404
        assert fake.started and fake.closed

    asyncio.run(case())


def test_selectors_strict_bodies_and_scope_visibility(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path, probe=True)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
                headers={"Authorization": "Bearer good"},
            ) as client:
                for selector in ("database", "repository", "store", "issuer", "principal"):
                    response = await client.get("/v1/whoami", params={selector: "other"})
                    assert response.status_code == 400
                response = await client.get("/v1/whoami", headers={"X-C1-Repository": "other"})
                assert response.status_code == 400
                scopes = await client.get("/v1/access-scopes")
                assert scopes.status_code == 200
                assert scopes.json()["access_scopes"] == [
                    {"id": _SCOPE, "label": "admin", "state": "active"}
                ]
                rejected = await client.post(
                    "/v1/access-scopes", json={"label": "synthetic", "database": "other"}
                )
                assert rejected.status_code == 400
                assert fake.operations.calls == []
                allowed = await client.post("/v1/access-scopes", json={"label": "synthetic"})
                assert allowed.status_code == 201
                assert fake.operations.calls == [("create_scope", "synthetic")]
                member = await client.post(
                    f"/v1/access-scopes/{_SCOPE}/members",
                    json={"member": _OTHER.id, "role": "reader"},
                )
                assert member.status_code == 200
                revoked = await client.delete(
                    f"/v1/access-scopes/{_SCOPE}/members/{_OTHER.id}",
                    params={"role": "reader"},
                )
                assert revoked.status_code == 200

                async def oversized() -> Any:
                    yield b'{"label":"'
                    yield b"x" * (1024 * 1024)
                    yield b'"}'

                too_large = await client.post(
                    "/v1/access-scopes",
                    content=oversized(),
                    headers={"Content-Type": "application/json"},
                )
                assert too_large.status_code == 413
                assert too_large.json()["type"] == "about:blank#validation"
                record = _record().model_dump(mode="json")
                forged = await client.post(
                    "/v1/probe/resources",
                    json={"record": record, "scope_id": _SCOPE, "grants": [_OTHER.id]},
                )
                assert forged.status_code == 400
                assert not any(call[0] == "provision" for call in fake.operations.calls)

    asyncio.run(case())


def test_probe_read_hides_missing_and_history_and_rejects_wrong_revision_id(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path, probe=True)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
                headers={"Authorization": "Bearer good"},
            ) as client:
                visible = await client.get("/v1/probe/resources/" + _RESOURCE)
                assert visible.status_code == 200
                assert visible.json()["id"] == _RESOURCE
                missing = await client.get("/v1/probe/resources/urn:c1:probe:entity/missing")
                hidden = await client.get(
                    "/v1/probe/resources/" + _RESOURCE, params={"revision": "hidden"}
                )
                assert missing.status_code == hidden.status_code == 404
                assert missing.content == hidden.content
                wrong = _record().model_copy(update={"id": "urn:c1:probe:entity/other"})
                rejected = await client.put(
                    "/v1/probe/resources/" + _RESOURCE,
                    json={"record": wrong.model_dump(mode="json")},
                )
                assert rejected.status_code == 400
                assert not any(call[0] == "revise_probe" for call in fake.operations.calls)

    asyncio.run(case())
