"""M13 harness: drive the reference deployment through its TLS endpoint only.

`fresh_deployment()` deletes and re-bootstraps `c1-ref`. Synthetic test users
and service clients are added with Keycloak's own admin CLI inside the Keycloak
container (test-only; the product realm template and bootstrap add none).
`ReferenceCase` offers the subset of the M03 `LiveCase` interface that the
fixture loaders use, so the M05–M11 fixtures load through the public API.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx

from c1.admin.net import mapped_client
from c1.authorization.principal import Principal

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "deployment/reference"
PROJECT = "c1-ref"
BASE = "https://c1.test:18443"
AUTH = "https://auth.c1.test:18443/realms/c1"
MAPPING = {"c1.test": "127.0.0.1", "auth.c1.test": "127.0.0.1"}
USERS = ("alice", "bob", "carol", "dave", "erin", "frank")
SERVICES = ("papertrader", "robotelier", "indexer", "analyzer", "ci")
AI_VARIABLES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "AZURE_OPENAI_API_KEY",
)
DEPLOYMENT_SETTINGS = (
    "# Non-secret deployment settings read by podman-compose (written by the M13 harness).\n"
    "C1_INSTANCE_ID=c1\n"
    "C1_INSTANCE_IRI_BASE=urn:c1:instance:dev:\n"
    "C1_QUERY_TIME_BUDGET_MS=30000\n"
    "C1_BACKEND_TIMEOUT_S=30\n"
    "C1_FGA_DEADLINE=30s\n"
)


def reference_enabled() -> bool:
    return os.environ.get("C1_REFERENCE") == "1"


def ca_file(directory: Path = DIR) -> Path:
    return directory / "certs/ca.pem"


def engine(*argv: str, input: bytes | None = None, check: bool = True) -> str:
    result = subprocess.run(["podman", *argv], input=input, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"podman {argv[0]} failed: {result.stderr.decode()[-500:]}")
    return result.stdout.decode()


def container(service: str, project: str = PROJECT) -> str:
    names = engine(
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        "{{.Names}}",
    ).split()
    assert len(names) == 1, (service, names)
    return names[0]


def admin(*argv: str, directory: Path = DIR, project: str = PROJECT) -> dict[str, Any]:
    """Run a host `c1-admin` command and return its JSON result."""
    result = subprocess.run(
        ["uv", "run", "--locked", "c1-admin", *argv, "--dir", str(directory), "--project", project],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"c1-admin {argv[0]} failed: {result.stderr.decode()[-1500:]}")
    return cast(dict[str, Any], json.loads(result.stdout))


def admin_internal_state() -> dict[str, Any]:
    return admin("status")


def compose(*argv: str, directory: Path = DIR, project: str = PROJECT) -> None:
    subprocess.run(
        ["podman-compose", "-p", project, "-f", str(directory / "compose.yaml"), *argv],
        cwd=directory,
        capture_output=True,
        check=True,
    )


def teardown(directory: Path = DIR, project: str = PROJECT) -> None:
    subprocess.run(
        ["podman-compose", "-p", project, "-f", str(directory / "compose.yaml"), "down", "-v"],
        cwd=directory,
        capture_output=True,
        check=False,
    )
    for name in engine("volume", "ls", "--format", "{{.Name}}").split():
        if name.startswith(project + "_"):
            engine("volume", "rm", "-f", name, check=False)


def fresh_deployment() -> dict[str, Any]:
    """A clean reference deployment: no state, secrets, certificates or volumes."""
    teardown()
    for name in ("state", "secrets", "certs"):
        subprocess.run(["rm", "-rf", str(DIR / name)], check=True)
    (DIR / ".env").write_text(DEPLOYMENT_SETTINGS)
    result = subprocess.run(
        ["uv", "run", "--locked", "c1-admin", "bootstrap", "--no-temporary-password"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("bootstrap failed: " + result.stderr.decode()[-2000:])
    return cast(dict[str, Any], json.loads(result.stdout))


# --- Test identities (Keycloak admin CLI inside the Keycloak container) -------


def _kcadm(*argv: str, input: bytes | None = None) -> str:
    keycloak = container("keycloak")
    return engine(
        "exec",
        "-i",
        keycloak,
        "/opt/keycloak/bin/kcadm.sh",
        *argv,
        "--config",
        "/tmp/kcadm.config",
        input=input,
    )


def provision_identities() -> dict[str, Any]:
    """Synthetic users, a direct-grant test client and service clients (test only)."""
    password = (DIR / "secrets/keycloak_admin_password").read_text().strip()
    _kcadm(
        "config",
        "credentials",
        "--server",
        "http://localhost:8080",
        "--realm",
        "master",
        "--user",
        "c1-bootstrap-admin",
        "--password",
        password,
    )
    kind: dict[str, Any] = {
        "name": "c1-principal-kind",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-hardcoded-claim-mapper",
        "config": {
            "claim.name": "c1_principal_kind",
            "claim.value": "human",
            "jsonType.label": "String",
            "access.token.claim": "true",
            "id.token.claim": "false",
            "userinfo.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }
    audience = {
        "name": "c1-api-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": "c1-api",
            "access.token.claim": "true",
            "id.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }
    tester = {
        "clientId": "c1-acceptance-tests",
        "enabled": True,
        "publicClient": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "protocolMappers": [kind, audience],
    }
    _kcadm("create", "clients", "-r", "c1", "-f", "-", input=json.dumps(tester).encode())
    identities: dict[str, Any] = {"users": {}, "services": {}}
    for user in USERS:
        value = secrets.token_urlsafe(18)
        _kcadm(
            "create",
            "users",
            "-r",
            "c1",
            "-s",
            f"username={user}",
            "-s",
            "enabled=true",
            "-s",
            "emailVerified=true",
            "-s",
            f"email={user}@example.invalid",
            "-s",
            f"firstName={user.title()}",
            "-s",
            "lastName=Example",
        )
        _kcadm("set-password", "-r", "c1", "--username", user, "--new-password", value)
        identities["users"][user] = value
    service_kind = {**kind, "config": {**kind["config"], "claim.value": "service"}}
    for service in SERVICES:
        client_id = f"c1-svc-{service}"
        client = {
            "clientId": client_id,
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "protocolMappers": [service_kind, audience],
        }
        _kcadm("create", "clients", "-r", "c1", "-f", "-", input=json.dumps(client).encode())
        internal = json.loads(_kcadm("get", "clients", "-r", "c1", "-q", f"clientId={client_id}"))
        secret = json.loads(
            _kcadm("get", f"clients/{internal[0]['id']}/client-secret", "-r", "c1")
        )["value"]
        identities["services"][client_id] = secret
    identities["admin"] = {
        "username": "c1admin",
        "password": (DIR / "secrets/admin_password").read_text().strip(),
    }
    path = DIR / "state/test-identities.json"
    path.write_text(json.dumps(identities))
    path.chmod(0o600)
    return identities


# --- Clients and tokens ----------------------------------------------------


@dataclass
class Token:
    access: str


@dataclass
class ReferenceTokens:
    identities: dict[str, Any]
    auth: str = AUTH
    _cache: dict[str, tuple[float, str]] = field(default_factory=dict)

    async def _issue(self, key: str, form: dict[str, str]) -> Token:
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return Token(cached[1])
        async with mapped_client(self.auth, mapping=MAPPING, ca_file=ca_file()) as client:
            response = await client.post(f"{self.auth}/protocol/openid-connect/token", data=form)
        if response.status_code != 200:
            raise RuntimeError(f"token request for {key} failed: {response.text[:300]}")
        body = response.json()
        self._cache[key] = (time.monotonic() + int(body["expires_in"]) - 60, body["access_token"])
        return Token(body["access_token"])

    async def user(self, name: str) -> Token:
        if name == "c1admin":
            password = self.identities["admin"]["password"]
        else:
            password = self.identities["users"][name]
        return await self._issue(
            "user:" + name,
            {
                "grant_type": "password",
                "client_id": "c1-acceptance-tests",
                "username": name,
                "password": password,
            },
        )

    async def service(self, client_id: str) -> Token:
        return await self._issue(
            "svc:" + client_id,
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": self.identities["services"][client_id],
            },
        )


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return cast(dict[str, Any], json.loads(base64.urlsafe_b64decode(payload + "=" * 4)))


class _Validator:
    async def authenticate(self, token: str) -> Principal:
        claims = _claims(token)
        return Principal(issuer_alias="c1", subject=claims["sub"], kind=claims["c1_principal_kind"])


class _Knowledge:
    def __init__(self, case: ReferenceCase) -> None:
        self.case = case

    async def head(self) -> str:
        response = await self.case.request("GET", "/v1/instance", actor="erin")
        assert response.status_code == 200, response.text
        return str(response.json()["knowledge_revision"])


@dataclass
class _Settings:
    instance_base: str = "urn:c1:instance:dev:"
    instance_id: str = "c1"


class ReferenceCase:
    """The LiveCase subset that fixture loaders use, over the TLS endpoint."""

    def __init__(self, identities: dict[str, Any], *, base: str = BASE, auth: str = AUTH) -> None:
        self.token_source = ReferenceTokens(identities, auth)
        self.client = mapped_client(base, mapping=MAPPING, ca_file=ca_file(), timeout=600)
        self.validator = _Validator()
        self.knowledge = _Knowledge(self)
        self.settings = _Settings()
        self.tokens: dict[str, str] = {}

    async def close(self) -> None:
        await self.client.aclose()

    async def token(self, name: str) -> str:
        return (await self.token_source.user(name)).access

    async def principal(self, name: str) -> Principal:
        return await self.validator.authenticate(await self.token(name))

    async def request(
        self, method: str, path: str, *, actor: str = "erin", **kwargs: Any
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + await self.token(actor)
        return await self.client.request(method, path, headers=headers, **kwargs)

    async def scope(self, label: str) -> str:
        response = await self.request("POST", "/v1/access-scopes", json={"label": label})
        assert response.status_code == 201, response.text
        value = str(response.json()["id"])
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


async def instance_roles(case: ReferenceCase) -> None:
    """The development stack's instance grants, made by the first administrator."""
    for member, role in (("erin", "access_admin"), ("frank", "access_admin"), ("dave", "operator")):
        principal = await case.principal(member)
        response = await case.request(
            "POST",
            "/v1/instance/grants",
            actor="c1admin",
            json={"member": principal.id, "role": role},
        )
        assert response.status_code == 200, response.text
