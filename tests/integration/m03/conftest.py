"""M03 integration helpers always use the pinned real identity/security stack."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from c1.authorization.fga import FGA
from c1.authorization.journal import Journal
from c1.authorization.principal import Principal
from c1.authorization.tokens import TokenValidator
from c1.config import Settings
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import StorageConfig, Terminus
from probes.config import environment

KEYCLOAK = "http://127.0.0.1:18090"
REALM = "c1-dev"
TOKEN_URL = f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token"
ROOT = Path(__file__).resolve().parents[3]
C1 = "urn:c1:ns:core#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCT = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
OA = "http://www.w3.org/ns/oa#"


def query_time_budget_ms() -> int:
    """The live request budget; C1_QUERY_TIME_BUDGET_MS overrides the product default."""
    return int(os.environ.get("C1_QUERY_TIME_BUDGET_MS", "5000"))


def client_timeout() -> float:
    """Keep the harness client deadline above the server budget it observes."""
    return query_time_budget_ms() / 1000 + 10


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m03/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M03 real services require C1_STACK=1"))


@dataclass(frozen=True)
class TokenPair:
    access: str
    identity: str | None = None


class TokenSource:
    """Fetch real Keycloak tokens without printing credentials or token bytes."""

    def __init__(self) -> None:
        self._private = environment()
        self._client = httpx.AsyncClient(timeout=10, trust_env=False)

    async def __aenter__(self) -> TokenSource:
        return self

    async def __aexit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        await self._client.aclose()

    def _secret(self, key: str) -> str:
        value = self._private.get(key)
        if not value:
            raise RuntimeError(f"M03 test credential {key} is missing")
        return value

    async def _issue(self, realm: str, form: dict[str, str]) -> TokenPair:
        response = await self._client.post(
            f"{KEYCLOAK}/realms/{realm}/protocol/openid-connect/token", data=form
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("Keycloak did not return an access token")
        identity = payload.get("id_token")
        return TokenPair(
            access=payload["access_token"],
            identity=identity if isinstance(identity, str) else None,
        )

    async def user(
        self,
        name: str,
        *,
        client: str = "c1-dev-tests",
        scope: str | None = None,
        realm: str = REALM,
    ) -> TokenPair:
        client_keys = {
            "c1-dev-tests": "C1_DEV_TESTS_SECRET",
            "c1-noaud": "C1_NOAUD_SECRET",
            "c1-shortlived": "C1_SHORTLIVED_SECRET",
            "c1-other-tests": "C1_OTHER_TESTS_SECRET",
        }
        password_key = (
            "C1_OTHER_USER_PASSWORD" if realm != REALM else f"C1_USER_{name.upper()}_PASSWORD"
        )
        form = {
            "grant_type": "password",
            "client_id": client,
            "client_secret": self._secret(client_keys[client]),
            "username": name,
            "password": self._secret(password_key),
        }
        if scope is not None:
            form["scope"] = scope
        return await self._issue(realm, form)

    async def service(self, client: str) -> TokenPair:
        secrets = {
            "c1-svc-papertrader": "C1_SVC_PAPERTRADER_SECRET",
            "c1-svc-robotelier": "C1_SVC_ROBOTELIER_SECRET",
        }
        return await self._issue(
            REALM,
            {
                "grant_type": "client_credentials",
                "client_id": client,
                "client_secret": self._secret(secrets[client]),
            },
        )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def resource_path(identifier: str) -> str:
    return "/v1/probe/resources/" + quote(identifier, safe="")


def entity_record(
    identifier: str | None = None,
    *,
    label: str = "Synthetic entity",
    scope_hint: str | None = None,
    project: str | None = None,
) -> NodeRecord:
    properties: dict[str, list[str | LiteralValue]] = {
        SKOS + "prefLabel": [
            LiteralValue(
                lexical=label,
                datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                language="en",
            )
        ],
        C1 + "lifecycle": [LiteralValue(lexical="active", datatype=XSD + "string")],
    }
    if scope_hint is not None:
        properties[C1 + "provisionedScopeHint"] = [scope_hint]
    if project is not None:
        properties[C1 + "projectReference"] = [project]
    return NodeRecord(
        id=identifier or "urn:c1:probe:entity-" + uuid.uuid4().hex,
        types=[C1 + "Entity"],
        properties=properties,
    )


def relation_record(subject: str, object_id: str, actor: str) -> NodeRecord:
    return NodeRecord(
        id="urn:c1:probe:assertion-" + uuid.uuid4().hex,
        types=[C1 + "Assertion"],
        properties={
            RDF + "subject": [subject],
            RDF + "predicate": [C1 + "worksFor"],
            RDF + "object": [object_id],
            C1 + "origin": [LiteralValue(lexical="manual", datatype=XSD + "string")],
            C1 + "reviewState": [LiteralValue(lexical="reported", datatype=XSD + "string")],
            C1 + "lifecycle": [LiteralValue(lexical="active", datatype=XSD + "string")],
            C1 + "manualStatement": [LiteralValue(lexical="true", datatype=XSD + "boolean")],
            PROV + "wasAttributedTo": [actor],
        },
    )


def source_record() -> NodeRecord:
    return NodeRecord(
        id="urn:c1:probe:source-" + uuid.uuid4().hex,
        types=[C1 + "Source"],
        properties={
            DCT + "title": [LiteralValue(lexical="Synthetic source", datatype=XSD + "string")],
            C1 + "sourceKind": [LiteralValue(lexical="fixture", datatype=XSD + "string")],
            C1 + "sourceRevision": [LiteralValue(lexical="fixture-r1", datatype=XSD + "string")],
        },
    )


def evidence_record(assertion: str, source: str) -> NodeRecord:
    return NodeRecord(
        id="urn:c1:probe:evidence-" + uuid.uuid4().hex,
        types=[C1 + "Evidence"],
        properties={
            C1 + "assertionRef": [assertion],
            OA + "hasSource": [source],
            C1 + "sourceRevision": [LiteralValue(lexical="fixture-r1", datatype=XSD + "string")],
            C1 + "excerpt": [LiteralValue(lexical="Synthetic excerpt", datatype=XSD + "string")],
        },
    )


def document_record() -> NodeRecord:
    return NodeRecord(
        id="urn:c1:probe:document-" + uuid.uuid4().hex,
        types=[C1 + "Document"],
        properties={
            DCT + "title": [LiteralValue(lexical="Synthetic document", datatype=XSD + "string")],
        },
    )


def part_record(document: str) -> NodeRecord:
    return NodeRecord(
        id="urn:c1:probe:part-" + uuid.uuid4().hex,
        types=[C1 + "DocumentPart"],
        properties={
            C1 + "partOfDocument": [document],
            C1 + "orderKey": [LiteralValue(lexical="001", datatype=XSD + "string")],
            C1 + "text": [LiteralValue(lexical="Synthetic part text", datatype=XSD + "string")],
        },
    )


@dataclass
class LiveCase:
    settings: Settings
    fga: FGA
    journal: Journal
    knowledge: Terminus
    client: httpx.AsyncClient
    token_source: TokenSource
    validator: TokenValidator
    tokens: dict[str, str]
    runtime: Any

    async def token(self, name: str) -> str:
        if name not in self.tokens:
            self.tokens[name] = (await self.token_source.user(name)).access
        return self.tokens[name]

    async def principal(self, name: str) -> Principal:
        return await self.validator.authenticate(await self.token(name))

    async def request(
        self, method: str, path: str, *, actor: str = "erin", **kwargs: Any
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers.update(bearer(await self.token(actor)))
        return await self.client.request(method, path, headers=headers, **kwargs)

    async def scope(self, label: str) -> str:
        response = await self.request("POST", "/v1/access-scopes", json={"label": label})
        assert response.status_code == 201, response.text
        value = response.json()["id"]
        assert isinstance(value, str)
        for role in ("creator", "contributor", "reader"):
            await self.grant(value, "erin", role)
        return value

    async def grant(self, scope: str, member: str, role: str) -> None:
        principal = await self.principal(member)
        response = await self.request(
            "POST",
            f"/v1/access-scopes/{quote(scope, safe='')}/members",
            json={"member": principal.id, "role": role},
        )
        assert response.status_code == 200, response.text

    async def provision(
        self, record: NodeRecord, scope: str, *, actor: str = "erin"
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            "/v1/probe/resources",
            actor=actor,
            json={"record": record.model_dump(mode="json"), "scope_id": scope},
        )
        assert response.status_code == 201, response.text
        value = response.json()
        assert isinstance(value, dict)
        return value


@asynccontextmanager
async def live_case() -> AsyncIterator[LiveCase]:
    """Give each test fresh knowledge/workflow databases and its own FGA store."""
    private = environment()
    password = private.get("C1_TERMINUS_PASSWORD")
    fga_token = private.get("C1_FGA_TOKEN")
    if not password or not fga_token:
        raise RuntimeError("M03 real stack credentials are missing")
    suffix = uuid.uuid4().hex
    async with FGA("http://127.0.0.1:18080", fga_token) as fga:
        await fga.create_store("c1-m03-" + suffix)
        try:
            settings = Settings(
                instance_id="m03_" + suffix,
                instance_base="urn:c1:instance:dev:",
                issuer=KEYCLOAK + "/realms/c1-dev",
                issuer_alias="c1-dev",
                audience="c1-api",
                fga_url="http://127.0.0.1:18080",
                fga_token=fga_token,
                fga_store=fga.store_id,
                fga_model=fga.model_id,
                terminus_url="http://127.0.0.1:16363",
                terminus_password=password,
                organization="admin",
                knowledge_database="c1_m03_k_" + suffix,
                workflow_database="c1_m03_w_" + suffix,
                lock_path=ROOT / "deployment/.state" / ("m03_" + suffix + ".lock"),
                independent_review=True,
                enable_probe_routes=True,
                cursor_secret=uuid.uuid4().hex + uuid.uuid4().hex,
                query_time_budget_ms=query_time_budget_ms(),
            )
            knowledge_config = StorageConfig(
                settings.terminus_url,
                settings.terminus_password,
                settings.organization,
                settings.knowledge_database,
                settings.instance_base,
            )
            workflow_config = StorageConfig(
                settings.terminus_url,
                settings.terminus_password,
                settings.organization,
                settings.workflow_database,
                settings.instance_base,
            )
            async with Terminus(knowledge_config) as knowledge:
                await knowledge.create()
                try:
                    await knowledge.install_profile(ProfileRegistry())
                    async with Journal(workflow_config) as journal:
                        await journal.initialize()
                        try:
                            async with TokenSource() as token_source:
                                validator = TokenValidator(settings)
                                try:
                                    tokens: dict[str, str] = {}
                                    grants: list[tuple[str, str, str]] = []
                                    for name, role in (
                                        ("erin", "access_admin"),
                                        ("frank", "access_admin"),
                                        ("dave", "operator"),
                                    ):
                                        tokens[name] = (await token_source.user(name)).access
                                        principal = await validator.authenticate(tokens[name])
                                        grants.append(
                                            (principal.id, role, "instance:" + settings.instance_id)
                                        )
                                    await fga.write(grants)
                                    from c1.api.app import create_app
                                    from c1.runtime import Runtime

                                    runtime = Runtime(settings)
                                    app = create_app(settings, runtime=runtime)
                                    async with app.router.lifespan_context(app):
                                        async with httpx.AsyncClient(
                                            transport=httpx.ASGITransport(app=app),
                                            base_url="http://c1.test",
                                            timeout=client_timeout(),
                                        ) as client:
                                            yield LiveCase(
                                                settings,
                                                fga,
                                                journal,
                                                knowledge,
                                                client,
                                                token_source,
                                                validator,
                                                tokens,
                                                runtime,
                                            )
                                finally:
                                    await validator.close()
                        finally:
                            await journal.drop_test_database()
                finally:
                    await knowledge.drop()
        finally:
            await fga.delete_store()
