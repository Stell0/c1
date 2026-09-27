"""M04 HTTP boundary checks with a service stub, not backend guarantees."""

import asyncio
from pathlib import Path
from typing import Any, cast

import httpx

from c1.api import create_app
from c1.authorization.principal import Principal
from c1.authorization.tokens import AuthenticationError
from c1.config import Settings
from c1.model.nodes import NodeRecord
from c1.runtime import Runtime

_PRINCIPAL = Principal("test", "alice", "human")
_RESOURCE = "urn:c1:instance:test:entity/one"
_PLACEHOLDER = "synthetic"


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


class _Changes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, method: str) -> Any:
        async def call(*args: Any) -> dict[str, Any]:
            self.calls.append((method, args))
            if method == "list":
                return {"changesets": []}
            if method == "history":
                return {"history": [], "next_cursor": None}
            if method == "create":
                return {"id": "cs-1", "replayed": args[2] == "replay"}
            return {"id": "cs-1", "action": method}

        return call


class _Knowledge:
    async def head(self) -> str:
        return "branch:synthetic-head"


class _Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tokens = _Tokens()
        self.audit = _Audit()
        self.changes = _Changes()
        self.knowledge = _Knowledge()
        self.ready_value = True
        self.ready_sequence: list[bool] = []

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def ready(self) -> bool:
        if self.ready_sequence:
            return self.ready_sequence.pop(0)
        return self.ready_value

    async def read(
        self, _principal: Principal, resource_id: str, revision: str | None = None
    ) -> NodeRecord | None:
        if resource_id != _RESOURCE or revision == "hidden":
            return None
        return NodeRecord(id=resource_id, types=["urn:c1:ns:core#Entity"], properties={})


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        instance_id="c1test",
        instance_base="urn:c1:instance:test:",
        issuer="http://127.0.0.1:18090/realms/test",
        issuer_alias="test",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token=_PLACEHOLDER,
        fga_store="test-store",
        fga_model="test-model",
        terminus_url="http://127.0.0.1:16363",
        terminus_password=_PLACEHOLDER,
        organization="admin",
        knowledge_database="knowledge_test",
        workflow_database="workflow_test",
        lock_path=tmp_path / "lock",
    )


def test_changeset_routes_enforce_transport_contract(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        headers = {"Authorization": "Bearer good"}
        body = {
            "base_revision": "branch:test",
            "operations": [{"kind": "install_profile", "profile": "example-vehicle"}],
        }
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                assert (await client.post("/v1/changesets", json=body)).status_code == 401
                assert (
                    await client.post("/v1/changesets", json=body, headers=headers)
                ).status_code == 400
                assert (
                    await client.post(
                        "/v1/changesets",
                        json={**body, "on_behalf_of": "user:test.bob"},
                        headers={**headers, "Idempotency-Key": "one"},
                    )
                ).status_code == 400
                created = await client.post(
                    "/v1/changesets",
                    json=body,
                    headers={**headers, "Idempotency-Key": "one"},
                )
                assert created.status_code == 201
                assert created.json()["id"] == "cs-1"
                replay = await client.post(
                    "/v1/changesets",
                    json=body,
                    headers={**headers, "Idempotency-Key": "replay"},
                )
                assert replay.status_code == 200
                assert replay.json()["replayed"] is True
                assert (
                    await client.post(
                        "/v1/changesets",
                        json=body,
                        headers={**headers, "Idempotency-Key": "x" * 129},
                    )
                ).status_code == 400
                assert (
                    await client.post(
                        "/v1/changesets/cs-1/apply", headers=headers, json={"extra": 1}
                    )
                ).status_code == 400
                assert (
                    await client.post("/v1/changesets/cs-1/apply", headers=headers, json={})
                ).status_code == 400
                assert (
                    await client.post(
                        "/v1/changesets/cs-1/apply",
                        headers={**headers, "Idempotency-Key": "apply-1"},
                        json={},
                    )
                ).status_code == 200
                assert (
                    await client.post(
                        "/v1/changesets/cs-1/rebase", headers=headers, json={"base_revision": "h2"}
                    )
                ).status_code == 200
                assert (await client.get("/v1/changesets/cs-1/validation", headers=headers)).json()[
                    "action"
                ] == "get_validation"
                assert (await client.get("/v1/changesets/cs-1", headers=headers)).json()[
                    "action"
                ] == "get"
                assert (await client.get("/v1/changesets", headers=headers)).json() == {
                    "changesets": []
                }
                assert (
                    await client.put(
                        "/v1/changesets/cs-1/operations",
                        headers=headers,
                        json={"operations": body["operations"]},
                    )
                ).json()["action"] == "edit"
                for action in ("submit", "validate", "approve", "withdraw"):
                    response = await client.post(
                        f"/v1/changesets/cs-1/{action}", headers=headers, json={}
                    )
                    assert response.status_code == 200
                    assert response.json()["action"] == action
                assert (
                    await client.post(
                        "/v1/changesets/cs-1/reject", headers=headers, json={"reason": "test"}
                    )
                ).json()["action"] == "reject"
                assert (
                    await client.get("/v1/changesets?principal=user:test.bob", headers=headers)
                ).status_code == 400
                assert (
                    await client.post(
                        "/v1/changesets",
                        headers={**headers, "Idempotency-Key": "large"},
                        json={**body, "rationale": "x" * (1024 * 1024)},
                    )
                ).status_code == 413
        assert fake.changes.calls[0][0] == "create"
        assert any(event["operation"] == "changeset_apply" for event in fake.audit.events)
        assert all(event["correlation_id"] for event in fake.audit.events)

    asyncio.run(case())


def test_resource_and_history_routes_restrict_query_parameters(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        headers = {"Authorization": "Bearer good"}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                visible = await client.get(f"/v1/resources/{_RESOURCE}", headers=headers)
                assert visible.status_code == 200
                hidden = await client.get(
                    f"/v1/resources/{_RESOURCE}?revision=hidden", headers=headers
                )
                missing = await client.get("/v1/resources/missing", headers=headers)
                assert hidden.status_code == missing.status_code == 404
                assert hidden.json() == missing.json()
                assert (
                    await client.get(
                        f"/v1/resources/{_RESOURCE}?revision=h1&revision=h2", headers=headers
                    )
                ).status_code == 400
                assert (
                    await client.get(
                        "/v1/history", params={"resource_id": _RESOURCE}, headers=headers
                    )
                ).status_code == 200
                assert (
                    await client.get(
                        "/v1/history",
                        params={"resource_id": _RESOURCE, "limit": 101},
                        headers=headers,
                    )
                ).status_code == 400
                assert (
                    await client.get("/v1/history", params={"cursor": "x"}, headers=headers)
                ).status_code == 400
                assert (
                    await client.get(
                        "/v1/history",
                        params={"resource_id": _RESOURCE, "database": "other"},
                        headers=headers,
                    )
                ).status_code == 400
        assert any(event["operation"] == "resource_history" for event in fake.audit.events)

    asyncio.run(case())


def test_instance_revision_requires_authentication_and_readiness(tmp_path: Path) -> None:
    async def case() -> None:
        settings = _settings(tmp_path)
        fake = _Runtime(settings)
        app = create_app(settings, runtime=cast(Runtime, fake))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                assert (await client.get("/v1/instance")).status_code == 401
                fake.ready_value = False
                unavailable = await client.get(
                    "/v1/instance", headers={"Authorization": "Bearer good"}
                )
                assert unavailable.status_code == 503
                assert "knowledge_revision" not in unavailable.json()
                fake.ready_value = True
                fake.ready_sequence = [True, False]
                unpublished = await client.get(
                    "/v1/instance", headers={"Authorization": "Bearer good"}
                )
                assert unpublished.status_code == 503
                assert "knowledge_revision" not in unpublished.json()
                visible = await client.get("/v1/instance", headers={"Authorization": "Bearer good"})
                assert visible.status_code == 200
                assert visible.json() == {
                    "instance_id": settings.instance_id,
                    "instance_base": settings.instance_base,
                    "knowledge_revision": "branch:synthetic-head",
                }

    asyncio.run(case())
