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
from probes.config import KEYCLOAK_URL, ROOT, environment  # noqa: E402

API_URL = "http://127.0.0.1:18000"
REALM = "c1-dev"
FIXTURE_PATH = ROOT / "fixtures/directory/fixture.json"


def _api_timeout() -> float:
    """Stay above the configured server request budget (default 5 s)."""
    budget_ms = int(os.environ.get("C1_QUERY_TIME_BUDGET_MS", "10000"))
    return max(20.0, budget_ms / 1000 + 10)


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
            base_url=configured_url, timeout=_api_timeout(), trust_env=False
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
            timeout=_api_timeout(),
            trust_env=False,
        ) as client:
            yield client


# Service actors authenticate with client credentials of `c1-svc-<producer>`.
SERVICE_ACTORS = {
    "service": "papertrader",
    "robotelier": "robotelier",
    "indexer": "indexer",
    "analyzer": "analyzer",
    "ci": "ci",
}


class Loader:
    def __init__(
        self, client: httpx.AsyncClient, tokens: dict[str, str], *, refresh_tokens: bool = False
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.refresh_tokens = refresh_tokens

    @classmethod
    async def connect(cls, client: httpx.AsyncClient) -> Loader:
        return cls(client, {}, refresh_tokens=True)

    async def _actor_token(self, actor: str) -> str:
        if not self.refresh_tokens:
            return self.tokens[actor]
        if actor not in SERVICE_ACTORS:
            return await self.user_token({"admin": "erin", "reviewer": "carol"}.get(actor, actor))
        private = {**environment(), **os.environ}
        producer = SERVICE_ACTORS[actor]
        secret_key = "C1_SVC_" + producer.upper() + "_SECRET"
        secret = private.get(secret_key)
        if not secret:
            raise RuntimeError(f"Required local credential {secret_key} is missing")
        async with httpx.AsyncClient(timeout=20, trust_env=False) as identity_client:
            response = await identity_client.post(
                f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
                data={
                    "client_id": "c1-svc-" + producer,
                    "client_secret": secret,
                    "grant_type": "client_credentials",
                },
            )
        if response.status_code != 200:
            raise RuntimeError(f"Could not obtain local fixture token ({response.status_code})")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise RuntimeError("Identity provider returned no access token")
        return token

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
        headers = {"Authorization": "Bearer " + await self._actor_token(actor)}
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

    async def _membership(
        self, scope_id: str, member: str, role: str, *, actor: str = "admin"
    ) -> None:
        await self.request(
            "POST",
            f"/v1/access-scopes/{quote(scope_id, safe='')}/members",
            actor=actor,
            json_body={"member": member, "role": role},
        )

    async def apply_changeset(
        self,
        operations: list[dict[str, Any]],
        *,
        author: str,
        reviewer: str,
        base: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Run the reviewed lifecycle and resume it after a retry.

        With a stable ``idempotency_key`` a repeated call replays the proposal
        and continues from its current state instead of creating a duplicate.
        """
        proposal = await self.request(
            "POST",
            "/v1/changesets",
            actor=author,
            json_body={
                "base_revision": base,
                "operations": operations,
                "rationale": "Load a deterministic synthetic fixture through ordinary C1 APIs",
            },
            expected=(200, 201),
            idempotency_key=idempotency_key or secrets.token_hex(16),
        )
        encoded = quote(str(proposal["id"]), safe="")
        current = await self.request("GET", f"/v1/changesets/{encoded}", actor=author)
        state = current.get("state")
        if state == "applied":
            return current
        if state == "draft":
            current = await self.request("POST", f"/v1/changesets/{encoded}/submit", actor=author)
            state = current.get("state")
        if state == "submitted":
            current = await self.request("POST", f"/v1/changesets/{encoded}/validate", actor=author)
            state = current.get("state")
        if state != "validated" and state != "approved":
            report = await self.request("GET", f"/v1/changesets/{encoded}/validation", actor=author)
            codes = [
                (item.get("code"), item.get("path"), item.get("message"))
                for item in report.get("diagnostics", [])
            ]
            raise RuntimeError(f"Fixture ChangeSet validation did not pass: {codes}")
        if state == "validated":
            current = await self.request(
                "POST", f"/v1/changesets/{encoded}/approve", actor=reviewer
            )
            if current.get("state") != "approved":
                raise RuntimeError("Fixture ChangeSet was not approved")
        applied = await self.request(
            "POST",
            f"/v1/changesets/{encoded}/apply",
            actor=reviewer,
            idempotency_key=(idempotency_key + "-apply")
            if idempotency_key
            else secrets.token_hex(16),
        )
        if applied.get("state") != "applied":
            raise RuntimeError("Fixture ChangeSet was not applied")
        return applied

    async def load_batteries(self, *, resume_setup: bool = False) -> dict[str, Any]:
        """Install the M07 fixture using two ordinary producers and Carol's review."""
        fixture = json.loads((ROOT / "fixtures/cross-project-batteries/fixture.json").read_text())
        await self.grant_instance(await self.whoami("admin"), "schema_admin")
        await self.grant_instance(await self.whoami("reviewer"), "schema_admin")
        installed = (
            (await self.request("GET", "/v1/catalog", actor="admin"))["profile_versions"]
            if resume_setup
            else {}
        )
        for name in ("topics", "batteries"):
            if name in installed:
                if installed[name] != fixture["version"]:
                    raise RuntimeError(f"Cannot resume with a different {name} profile version")
                continue
            # The writer accepts exactly one schema installation per proposal.
            # Resolve the new head after each independently reviewed install.
            await self.apply_changeset(
                [{"kind": "install_profile", "profile": name}],
                author="admin",
                reviewer="reviewer",
                base=(await self.request("GET", "/v1/instance", actor="admin"))[
                    "knowledge_revision"
                ],
            )
        existing_scopes = (
            {
                item["id"]: item
                for item in (await self.request("GET", "/v1/access-scopes", actor="admin"))[
                    "access_scopes"
                ]
            }
            if resume_setup
            else {}
        )
        scopes: dict[str, str] = {}
        principals = {
            actor: await self.whoami(actor)
            for actor in ("service", "robotelier", "reviewer", "dave")
        }
        for key, label in fixture["scopes"].items():
            if key in existing_scopes:
                if (
                    existing_scopes[key].get("label") != label
                    or existing_scopes[key].get("state") != "active"
                ):
                    raise RuntimeError("Cannot resume with a different or inactive fixture scope")
            else:
                await self.request(
                    "POST",
                    "/v1/access-scopes",
                    actor="admin",
                    json_body={"id": key, "label": label},
                    expected=(201,),
                )
            scopes[key] = key
            await self._membership(key, principals["reviewer"], "reader")
            await self._membership(key, principals["reviewer"], "reviewer")
            if key in fixture["principals"]["dave"]:
                await self._membership(key, principals["dave"], "reader")
        for actor, allowed in (
            ("service", ("bat-shared", "bat-papertrader")),
            ("robotelier", tuple(scopes)),
        ):
            for scope in allowed:
                for role in ("reader", "creator", "contributor"):
                    await self._membership(scope, principals[actor], role)
        producer_principals = {
            "papertrader": principals["service"],
            "robotelier": principals["robotelier"],
        }
        if resume_setup:
            existing = await self.request(
                "GET",
                "/v1/entities?ids=" + quote(fixture["ids"]["tesla"], safe=""),
                actor="reviewer",
            )
            if existing.get("items"):
                raise RuntimeError(
                    "--resume-setup only resumes before producer content was applied"
                )
        for producer, actor in (("papertrader", "service"), ("robotelier", "robotelier")):
            if producer == "robotelier":
                found = await self.request(
                    "GET", "/v1/entities?label=Tesla&label_mode=exact", actor=actor
                )
                candidates = found.get("items", [])
                if len(candidates) != 1 or candidates[0].get("id") != fixture["ids"]["tesla"]:
                    raise RuntimeError(
                        "Robotelier must resolve and reuse the visible Tesla identity"
                    )
            operations = fixture_operations(
                fixture["producers"][producer], scopes, producer_principals
            )
            await self.apply_changeset(
                operations,
                author=actor,
                reviewer="reviewer",
                base=(await self.request("GET", "/v1/instance", actor=actor))["knowledge_revision"],
            )
        return {
            "fixture": fixture,
            "scopes": scopes,
            "principals": producer_principals,
            "revision": (await self.request("GET", "/v1/instance", actor="reviewer"))[
                "knowledge_revision"
            ],
            "state": "applied",
        }


def fixture_operations(
    records: list[dict[str, Any]], scopes: dict[str, str], principals: dict[str, str]
) -> list[dict[str, Any]]:
    """Bind attributed producer placeholders to the authenticated actual principals."""
    operations = []
    for item in records:
        record = json.loads(json.dumps({key: item[key] for key in ("id", "types", "properties")}))
        actor_predicate = "http://www.w3.org/ns/prov#wasAttributedTo"
        values = record["properties"].get(actor_predicate, [])
        record["properties"][actor_predicate] = (
            [
                principals[value.removeprefix("urn:c1:fixture:producer:")]
                if isinstance(value, str) and value.startswith("urn:c1:fixture:producer:")
                else value
                for value in values
            ]
            if values
            else []
        )
        if not values:
            record["properties"].pop(actor_predicate, None)
        operations.append({"kind": "create", "record": record, "scope_id": scopes[item["scope"]]})
    return operations


async def load_cross_project_batteries(
    database: str | None, *, resume_setup: bool = False
) -> dict[str, str]:
    async with api_client(database) as client:
        value = await (await Loader.connect(client)).load_batteries(resume_setup=resume_setup)
        return {
            "fixture": value["fixture"]["name"],
            "state": value["state"],
            "revision": value["revision"],
        }


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
    parser.add_argument(
        "--fixture",
        choices=("directory", "scoped-document", "cross-project-batteries"),
        required=True,
    )
    parser.add_argument("--database", help="must match the trusted local knowledge database")
    parser.add_argument(
        "--resume-setup",
        action="store_true",
        help="reuse matching batteries profiles/scopes before producer content exists",
    )
    args = parser.parse_args()
    loader = {
        "directory": load,
        "scoped-document": load_scoped_document,
        "cross-project-batteries": load_cross_project_batteries,
    }[args.fixture]
    if args.resume_setup and args.fixture != "cross-project-batteries":
        parser.error("--resume-setup requires --fixture cross-project-batteries")
    result = (
        load_cross_project_batteries(args.database, resume_setup=True)
        if args.resume_setup
        else loader(args.database)
    )
    print(json.dumps(asyncio.run(result), sort_keys=True))


if __name__ == "__main__":
    main()
