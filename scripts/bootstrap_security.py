"""Bootstrap only the isolated c1-dev identity and authorization fixtures.

Realm files contain no credentials. This script writes generated values only to
the ignored, mode-0600 deployment/.env and never logs token or password text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

import httpx

from c1.authorization.journal import Journal
from c1.model.profiles import ProfileRegistry
from c1.storage.schema import assert_installed_profiles
from c1.storage.terminus import BackendError, StorageConfig, Terminus
from probes.config import ENV_FILE, ROOT, environment

KEYCLOAK_URL = "http://127.0.0.1:18090"
FGA_URL = "http://127.0.0.1:18080"
USERS = ("alice", "bob", "carol", "dave", "erin", "frank")
CLIENT_SECRETS = {
    "c1-api": "C1_API_CLIENT_SECRET",
    "c1-dev-tests": "C1_DEV_TESTS_SECRET",
    "c1-noaud": "C1_NOAUD_SECRET",
    "c1-shortlived": "C1_SHORTLIVED_SECRET",
    "c1-svc-papertrader": "C1_SVC_PAPERTRADER_SECRET",
    "c1-svc-robotelier": "C1_SVC_ROBOTELIER_SECRET",
    "c1-svc-indexer": "C1_SVC_INDEXER_SECRET",
    "c1-svc-analyzer": "C1_SVC_ANALYZER_SECRET",
    "c1-svc-ci": "C1_SVC_CI_SECRET",
    "c1-explorer": "C1_EXPLORER_CLIENT_SECRET",
}
BASE_SECRETS = (
    "C1_TERMINUS_PASSWORD",
    "C1_POSTGRES_PASSWORD",
    "C1_FGA_DB_PASSWORD",
    "C1_FGA_TOKEN",
    "C1_CURSOR_SECRET",
    "C1_KEYCLOAK_DB_PASSWORD",
    "C1_KEYCLOAK_ADMIN_PASSWORD",
)
USER_SECRETS = tuple(f"C1_USER_{name.upper()}_PASSWORD" for name in USERS) + (
    "C1_OTHER_USER_PASSWORD",
)
DEFAULTS = {
    "C1_INSTANCE_ID": "dev",
    "C1_INSTANCE_IRI_BASE": "urn:c1:instance:dev:",
    "C1_ISSUER": KEYCLOAK_URL + "/realms/c1-dev",
    "C1_ISSUER_ALIAS": "c1-dev",
    "C1_AUDIENCE": "c1-api",
    "C1_FGA_URL": FGA_URL,
    "C1_TERMINUS_URL": "http://127.0.0.1:16363",
    "C1_ORGANIZATION": "admin",
    "C1_KNOWLEDGE_DATABASE": "c1_m03_dev_knowledge",
    "C1_WORKFLOW_DATABASE": "c1_m03_dev_workflow",
    "C1_LOCK_PATH": str(ROOT / "deployment/.state/m03-writer.lock"),
    "C1_INDEPENDENT_REVIEW": "true",
    "C1_ENABLE_PROBE_ROUTES": "false",
}


def _save_env(values: dict[str, str]) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=".env.pending-", dir=ENV_FILE.parent)
    pending = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("# Private random development credentials; never commit this file.\n")
            for key, value in sorted(values.items()):
                if "\n" in key or "\n" in value or "=" in key:
                    raise ValueError("Unsafe environment value")
                stream.write(f"{key}={value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, ENV_FILE)
        ENV_FILE.chmod(0o600)
    finally:
        pending.unlink(missing_ok=True)


def ensure_environment() -> dict[str, str]:
    """Preserve prior M01 credentials and generate only missing local values."""

    values = environment()
    if ENV_FILE.exists() and ENV_FILE.stat().st_mode & 0o077:
        raise RuntimeError("deployment/.env must be mode 0600")
    changed = not ENV_FILE.exists()
    for key in (*BASE_SECRETS, *USER_SECRETS):
        if not values.get(key):
            values[key] = secrets.token_hex(24)
            changed = True
    for key, value in DEFAULTS.items():
        if not values.get(key):
            values[key] = value
            changed = True
    if changed:
        _save_env(values)
    return values


class _Admin:
    def __init__(self, client: httpx.Client, password: str) -> None:
        response = client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "c1-dev-admin",
                "password": password,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"Keycloak admin token failed ({response.status_code})")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise RuntimeError("Keycloak admin token missing")
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = self.client.request(
            method, path, headers=self.headers, json=json_body, params=params
        )
        if response.status_code >= 400 and not (method == "GET" and response.status_code == 404):
            raise RuntimeError(f"Keycloak {method} {path} failed ({response.status_code})")
        return response

    def ensure_realm(self, path: Path) -> dict[str, Any]:
        desired: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        realm = desired["realm"]
        response = self.request("GET", f"/admin/realms/{realm}")
        if response.status_code == 404:
            response = self.request("POST", "/admin/realms", json_body=desired)
            if response.status_code not in (201, 204):
                raise RuntimeError(f"Keycloak realm create failed ({response.status_code})")
        return desired

    def ensure_group(self, realm: str, name: str) -> str:
        path = f"/admin/realms/{realm}/groups"
        response = self.request("GET", path, params={"search": name, "exact": "true"})
        groups = response.json()
        found = [item for item in groups if item.get("name") == name]
        if not found:
            self.request("POST", path, json_body={"name": name})
            groups = self.request("GET", path, params={"search": name, "exact": "true"}).json()
            found = [item for item in groups if item.get("name") == name]
        if len(found) != 1:
            raise RuntimeError("Keycloak group lookup ambiguous")
        return str(found[0]["id"])

    def ensure_user(self, realm: str, name: str, password: str) -> str:
        path = f"/admin/realms/{realm}/users"
        params = {"username": name, "exact": "true"}
        users = self.request("GET", path, params=params).json()
        found = [item for item in users if item.get("username") == name]
        if not found:
            self.request("POST", path, json_body={"username": name, "enabled": True})
            users = self.request("GET", path, params=params).json()
            found = [item for item in users if item.get("username") == name]
        if len(found) != 1:
            raise RuntimeError("Keycloak user lookup ambiguous")
        user_id = str(found[0]["id"])
        self.request(
            "PUT",
            f"{path}/{user_id}",
            json_body={
                **found[0],
                "email": name + "@example.invalid",
                "firstName": name.title(),
                "lastName": "Example",
                "emailVerified": True,
                "requiredActions": [],
            },
        )
        self.request(
            "PUT",
            f"{path}/{user_id}/reset-password",
            json_body={"type": "password", "value": password, "temporary": False},
        )
        return user_id

    def ensure_client(self, realm: str, desired: dict[str, Any]) -> str:
        name = desired["clientId"]
        path = f"/admin/realms/{realm}/clients"
        clients = self.request("GET", path, params={"clientId": name}).json()
        found = [item for item in clients if item.get("clientId") == name]
        if not found:
            self.request("POST", path, json_body=desired)
            clients = self.request("GET", path, params={"clientId": name}).json()
            found = [item for item in clients if item.get("clientId") == name]
        if len(found) != 1:
            raise RuntimeError("Keycloak client lookup ambiguous")
        client_id = str(found[0]["id"])
        if name == "c1-m01-probe":
            return client_id
        current = self.request("GET", f"{path}/{client_id}").json()
        update = {**current, **{k: v for k, v in desired.items() if k != "protocolMappers"}}
        update.pop("secret", None)
        self.request("PUT", f"{path}/{client_id}", json_body=update)
        mapper_path = f"{path}/{client_id}/protocol-mappers/models"
        current_mappers = self.request("GET", mapper_path).json()
        by_name = {item["name"]: item for item in current_mappers}
        for mapper in desired.get("protocolMappers", []):
            existing = by_name.get(mapper["name"])
            if existing is None:
                self.request("POST", mapper_path, json_body=mapper)
            else:
                self.request(
                    "PUT", f"{mapper_path}/{existing['id']}", json_body={**existing, **mapper}
                )
        return client_id

    def client_secret(self, realm: str, client_id: str) -> str:
        path = f"/admin/realms/{realm}/clients/{client_id}/client-secret"
        response = self.request("GET", path)
        if response.status_code == 404 or not response.json().get("value"):
            response = self.request("POST", path)
        value = response.json().get("value")
        if not isinstance(value, str) or not value:
            raise RuntimeError("Keycloak client secret missing")
        return value


def _fga_request(
    client: httpx.Client, token: str, method: str, path: str, payload: object | None = None
) -> dict[str, Any]:
    response = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenFGA {method} {path} failed ({response.status_code})")
    return response.json() if response.content else {}


def _bootstrap_fga(values: dict[str, str], subjects: dict[str, str]) -> None:
    model_path = ROOT / "deployment/openfga/c1-v1.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    token = values["C1_FGA_TOKEN"]
    with httpx.Client(base_url=FGA_URL, timeout=10, trust_env=False) as client:
        store = values.get("C1_FGA_STORE")
        if not store:
            stores = _fga_request(client, token, "GET", "/stores").get("stores", [])
            matching = [item for item in stores if item.get("name") == "c1-dev"]
            if len(matching) > 1:
                raise RuntimeError("Multiple c1-dev OpenFGA stores")
            if matching:
                store = str(matching[0]["id"])
            else:
                store = str(
                    _fga_request(client, token, "POST", "/stores", {"name": "c1-dev"})["id"]
                )
            values["C1_FGA_STORE"] = store
            _save_env(values)
        else:
            _fga_request(client, token, "GET", f"/stores/{store}")
        model_text = json.dumps(model, sort_keys=True, separators=(",", ":"))
        model_digest = hashlib.sha256(model_text.encode()).hexdigest()
        if not values.get("C1_FGA_MODEL") or values.get("C1_FGA_MODEL_SHA256") != model_digest:
            response = _fga_request(
                client, token, "POST", f"/stores/{store}/authorization-models", model
            )
            values["C1_FGA_MODEL"] = str(response["authorization_model_id"])
            values["C1_FGA_MODEL_SHA256"] = model_digest
            _save_env(values)
        model_id = values["C1_FGA_MODEL"]
        # The .env digest describes the file used when the model was published;
        # also require the configured immutable model ID to still exist.
        _fga_request(client, token, "GET", f"/stores/{store}/authorization-models/{model_id}")
        instance = "instance:" + values["C1_INSTANCE_ID"]
        grants = [("erin", "access_admin"), ("frank", "access_admin"), ("dave", "operator")]
        writes = []
        for name, relation in grants:
            user = "user:c1-dev." + subjects[name]
            read = _fga_request(
                client,
                token,
                "POST",
                f"/stores/{store}/read",
                {"tuple_key": {"user": user, "relation": relation, "object": instance}},
            )
            if not read.get("tuples"):
                writes.append({"user": user, "relation": relation, "object": instance})
        if writes:
            _fga_request(
                client,
                token,
                "POST",
                f"/stores/{store}/write",
                {"writes": {"tuple_keys": writes}, "authorization_model_id": model_id},
            )
        for name, relation in grants:
            decision = _fga_request(
                client,
                token,
                "POST",
                f"/stores/{store}/check",
                {
                    "tuple_key": {
                        "user": "user:c1-dev." + subjects[name],
                        "relation": relation,
                        "object": instance,
                    },
                    "authorization_model_id": model_id,
                    "consistency": "HIGHER_CONSISTENCY",
                },
            )
            if decision.get("allowed") is not True:
                raise RuntimeError("OpenFGA bootstrap grant was not observed")


async def _bootstrap_databases(values: dict[str, str]) -> None:
    def config(database: str) -> StorageConfig:
        return StorageConfig(
            url=values["C1_TERMINUS_URL"],
            password=values["C1_TERMINUS_PASSWORD"],
            organization=values["C1_ORGANIZATION"],
            database=database,
            instance_base=values["C1_INSTANCE_IRI_BASE"],
        )

    registry = ProfileRegistry()
    async with Terminus(config(values["C1_KNOWLEDGE_DATABASE"])) as knowledge:
        try:
            await knowledge.head()
        except BackendError as exc:
            if exc.status_code != 404:
                raise
            await knowledge.create()
            await knowledge.install_profile(registry)
        await assert_installed_profiles(knowledge, registry)

    async with Journal(config(values["C1_WORKFLOW_DATABASE"])) as journal:
        try:
            await journal.head()
        except BackendError as exc:
            if exc.status_code != 404:
                raise
            await journal.initialize()
        else:
            await journal.migrate_records()  # M14b D4: pre-M14b journals
        if not await journal.ready():
            raise RuntimeError("Existing workflow database schema is not the C1 journal schema")


def bootstrap() -> None:
    values = ensure_environment()
    subjects: dict[str, str] = {}
    with httpx.Client(base_url=KEYCLOAK_URL, timeout=15, trust_env=False) as client:
        admin = _Admin(client, values["C1_KEYCLOAK_ADMIN_PASSWORD"])
        dev = admin.ensure_realm(ROOT / "deployment/keycloak/c1-dev-realm.json")
        other = admin.ensure_realm(ROOT / "deployment/keycloak/c1-other-realm.json")
        group_ids = {
            group["name"]: admin.ensure_group("c1-dev", group["name"]) for group in dev["groups"]
        }
        for item in dev["users"]:
            name = item["username"]
            subjects[name] = admin.ensure_user(
                "c1-dev", name, values[f"C1_USER_{name.upper()}_PASSWORD"]
            )
        admin.ensure_user("c1-other", "outsider", values["C1_OTHER_USER_PASSWORD"])
        for name, group in (("alice", "readers-shared"), ("erin", "admins"), ("frank", "admins")):
            admin.request(
                "PUT",
                f"/admin/realms/c1-dev/users/{subjects[name]}/groups/{group_ids[group]}",
            )
        for item in dev["clients"]:
            client_id = admin.ensure_client("c1-dev", item)
            if item["clientId"] in CLIENT_SECRETS:
                values[CLIENT_SECRETS[item["clientId"]]] = admin.client_secret("c1-dev", client_id)
        for item in other["clients"]:
            client_id = admin.ensure_client("c1-other", item)
            if item["clientId"] == "c1-other-tests":
                values["C1_OTHER_TESTS_SECRET"] = admin.client_secret("c1-other", client_id)
        _save_env(values)
    _bootstrap_fga(values, subjects)
    asyncio.run(_bootstrap_databases(values))
    print("c1-dev identity, authorization, and databases: ready")


if __name__ == "__main__":
    bootstrap()
