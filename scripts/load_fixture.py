"""Load the deterministic directory fixture through C1's authenticated API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probes.config import ROOT, environment  # noqa: E402

API_URL = "http://127.0.0.1:18000"
KEYCLOAK_URL = "http://127.0.0.1:18090"
REALM = "c1-dev"
FIXTURE_PATH = ROOT / "fixtures/directory/fixture.json"


@asynccontextmanager
async def api_client(database: str | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """Use an explicitly configured API or host the trusted local app in-process."""
    configured_url = os.environ.get("C1_API_URL")
    private = {**environment(), **os.environ}
    if configured_url:
        target = httpx.URL(configured_url)
        if (
            target.scheme != "http"
            or target.host not in {"127.0.0.1", "localhost"}
            or target.port != 18000
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
        ):
            raise RuntimeError("C1_API_URL must name the local C1 development API")
        if database and database != private.get("C1_KNOWLEDGE_DATABASE"):
            raise RuntimeError("--database must match C1_KNOWLEDGE_DATABASE")
        async with httpx.AsyncClient(
            base_url=configured_url, timeout=20, trust_env=False
        ) as client:
            yield client
        return

    if database and database != private.get("C1_KNOWLEDGE_DATABASE"):
        raise RuntimeError("--database must match trusted deployment/.env C1_KNOWLEDGE_DATABASE")
    for key, value in private.items():
        os.environ.setdefault(key, value)
    from c1.api.app import create_app
    from c1.config import Settings

    app = create_app(Settings.from_env())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://c1.local",
            timeout=20,
            trust_env=False,
        ) as client:
            yield client


class Loader:
    def __init__(self, client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
        self.client = client
        self.tokens = tokens

    @classmethod
    async def connect(cls, client: httpx.AsyncClient) -> Loader:
        private = {**environment(), **os.environ}

        async def issue(client_id: str, secret_key: str, *, username: str | None = None) -> str:
            secret = private.get(secret_key)
            if not secret:
                raise RuntimeError(f"Required local credential {secret_key} is missing")
            form = {
                "client_id": client_id,
                "client_secret": secret,
                "grant_type": "password" if username else "client_credentials",
            }
            if username:
                password_key = f"C1_USER_{username.upper()}_PASSWORD"
                password = private.get(password_key)
                if not password:
                    raise RuntimeError(f"Required local credential {password_key} is missing")
                form.update(username=username, password=password)
            async with httpx.AsyncClient(timeout=20, trust_env=False) as identity_client:
                response = await identity_client.post(
                    f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
                    data=form,
                )
            if response.status_code != 200:
                raise RuntimeError(f"Could not obtain local fixture token ({response.status_code})")
            token = response.json().get("access_token")
            if not isinstance(token, str):
                raise RuntimeError("Identity provider returned no access token")
            return token

        return cls(
            client,
            {
                "service": await issue("c1-svc-papertrader", "C1_SVC_PAPERTRADER_SECRET"),
                "admin": await issue("c1-dev-tests", "C1_DEV_TESTS_SECRET", username="erin"),
                "reviewer": await issue("c1-dev-tests", "C1_DEV_TESTS_SECRET", username="carol"),
            },
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        actor: str,
        json_body: object | None = None,
        expected: tuple[int, ...] = (200,),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": "Bearer " + self.tokens[actor]}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = await self.client.request(method, path, headers=headers, json=json_body)
        if response.status_code not in expected:
            raise RuntimeError(
                f"C1 {method} {path} returned {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            return {}
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError(f"C1 {method} {path} returned an unexpected response")
        return value

    async def whoami(self, actor: str) -> str:
        value = await self.request("GET", "/v1/whoami", actor=actor)
        alias, subject = value.get("issuer_alias"), value.get("subject")
        if not isinstance(alias, str) or not isinstance(subject, str):
            raise RuntimeError("C1 did not return a principal identity")
        return f"user:{alias}.{subject}"

    async def user_token(self, username: str) -> str:
        private = {**environment(), **os.environ}
        secret = private.get("C1_DEV_TESTS_SECRET")
        password = private.get(f"C1_USER_{username.upper()}_PASSWORD")
        if not secret or not password:
            raise RuntimeError(f"Required local credentials for {username} are missing")
        async with httpx.AsyncClient(timeout=20, trust_env=False) as identity_client:
            response = await identity_client.post(
                f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "c1-dev-tests",
                    "client_secret": secret,
                    "username": username,
                    "password": password,
                },
            )
        if response.status_code != 200:
            raise RuntimeError(f"Could not obtain local token for {username}")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise RuntimeError("Identity provider returned no access token")
        return token

    async def grant_instance(self, member: str, role: str) -> None:
        await self.request(
            "POST",
            "/v1/instance/grants",
            actor="admin",
            json_body={"member": member, "role": role},
        )

    async def create_scopes(
        self, fixture: dict[str, Any], *, scope_prefix: str = "directory"
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, label in fixture["scopes"].items():
            scope_id = scope_prefix + "_" + key.replace("-", "_")
            await self.request(
                "POST",
                "/v1/access-scopes",
                actor="admin",
                json_body={"id": scope_id, "label": label},
                expected=(201,),
            )
            values[key] = scope_id
        principal_ids = {name: await self._whoami_user(name) for name in ("alice", "bob", "dave")}
        principal_ids["carol"] = await self.whoami("reviewer")
        service_id = await self.whoami("service")
        for name, permitted in fixture["principals"].items():
            for scope_key in permitted:
                await self._membership(values[scope_key], principal_ids[name], "reader")
        for scope_id in values.values():
            await self._membership(scope_id, service_id, "creator")
            await self._membership(scope_id, service_id, "contributor")
            await self._membership(scope_id, service_id, "reader")
            await self._membership(scope_id, principal_ids["carol"], "reviewer")
        return values

    async def _whoami_user(self, name: str) -> str:
        token = await self.user_token(name)
        response = await self.client.get("/v1/whoami", headers={"Authorization": "Bearer " + token})
        if response.status_code != 200:
            raise RuntimeError(f"C1 could not resolve local principal {name}")
        value = response.json()
        return f"user:{value['issuer_alias']}.{value['subject']}"

    async def _membership(self, scope_id: str, member: str, role: str) -> None:
        await self.request(
            "POST",
            f"/v1/access-scopes/{quote(scope_id, safe='')}/members",
            actor="admin",
            json_body={"member": member, "role": role},
        )

    async def apply_changeset(
        self, operations: list[dict[str, Any]], *, author: str, reviewer: str, base: str
    ) -> dict[str, Any]:
        proposal = await self.request(
            "POST",
            "/v1/changesets",
            actor=author,
            json_body={
                "base_revision": base,
                "operations": operations,
                "rationale": "Load the deterministic directory demo fixture",
            },
            expected=(201,),
            idempotency_key=secrets.token_hex(16),
        )
        encoded = quote(str(proposal["id"]), safe="")
        submitted = await self.request("POST", f"/v1/changesets/{encoded}/submit", actor=author)
        if submitted.get("state") == "submitted":
            submitted = await self.request(
                "POST", f"/v1/changesets/{encoded}/validate", actor=author
            )
        if submitted.get("state") != "validated":
            raise RuntimeError("Directory ChangeSet validation did not pass")
        approved = await self.request("POST", f"/v1/changesets/{encoded}/approve", actor=reviewer)
        if approved.get("state") != "approved":
            raise RuntimeError("Directory ChangeSet was not approved")
        applied = await self.request(
            "POST",
            f"/v1/changesets/{encoded}/apply",
            actor=reviewer,
            idempotency_key=secrets.token_hex(16),
        )
        if applied.get("state") != "applied":
            raise RuntimeError("Directory ChangeSet was not applied")
        return applied


async def load(database: str | None) -> dict[str, str]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    async with api_client(database) as client:
        loader = await Loader.connect(client)
        await loader.grant_instance(await loader.whoami("admin"), "schema_admin")
        await loader.grant_instance(await loader.whoami("reviewer"), "schema_admin")
        await loader.apply_changeset(
            [{"kind": "install_profile", "profile": fixture["profile"]}],
            author="admin",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="admin"))["knowledge_revision"],
        )
        scopes = await loader.create_scopes(fixture)
        operations = []
        for item in fixture["records"]:
            record = {key: item[key] for key in ("id", "types", "properties")}
            operations.append(
                {"kind": "create", "record": record, "scope_id": scopes[item["scope"]]}
            )
        result = await loader.apply_changeset(
            operations,
            author="service",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="service"))[
                "knowledge_revision"
            ],
        )
        return {"fixture": fixture["name"], "state": str(result["state"])}


async def load_scoped_document(database: str | None) -> dict[str, str]:
    fixture_path = ROOT / "fixtures/scoped-document/fixture.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    async with api_client(database) as client:
        loader = await Loader.connect(client)
        await loader.grant_instance(await loader.whoami("admin"), "schema_admin")
        await loader.grant_instance(await loader.whoami("reviewer"), "schema_admin")
        scopes = await loader.create_scopes(fixture, scope_prefix="scoped_document")
        operations = []
        for item in fixture["revision1"]:
            record = {key: item[key] for key in ("id", "types", "properties")}
            operations.append(
                {"kind": "create", "record": record, "scope_id": scopes[item["scope"]]}
            )
        first = await loader.apply_changeset(
            operations,
            author="service",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="service"))[
                "knowledge_revision"
            ],
        )
        if first.get("state") != "applied":
            raise RuntimeError("Scoped document revision 1 was not applied")

        replacements = []
        by_id = {item["id"]: item for item in fixture["revision1"]}
        for change in fixture["revision2"]["changes"]:
            original = by_id.get(change["id"])
            if original is None:
                raise RuntimeError("Scoped document update references an unknown fixture record")
            record = {key: original[key] for key in ("id", "types", "properties")}
            record["properties"] = {**record["properties"], **change["properties"]}
            replacements.append(
                {
                    "kind": "replace",
                    "resource_id": change["id"],
                    "record": record,
                    "reason": "Load deterministic scoped document revision 2",
                }
            )
        second = await loader.apply_changeset(
            replacements,
            author="service",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="service"))[
                "knowledge_revision"
            ],
        )
        if second.get("state") != "applied":
            raise RuntimeError("Scoped document revision 2 was not applied")
        return {"fixture": fixture["name"], "state": str(second["state"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=("directory", "scoped-document"), required=True)
    parser.add_argument("--database", help="must match the trusted local knowledge database")
    args = parser.parse_args()
    loader = load if args.fixture == "directory" else load_scoped_document
    print(json.dumps(asyncio.run(loader(args.database)), sort_keys=True))


if __name__ == "__main__":
    main()
