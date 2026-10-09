"""Real external-provider fixture driven through the public operator interface."""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from tests.integration.m14c.providers import HydraIdentityUI

ROOT = Path(__file__).resolve().parents[3]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m14c/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_EXTERNAL") != "1":
                item.add_marker(
                    pytest.mark.skip(reason="M14c requires C1_EXTERNAL=1 and pinned services")
                )


class External:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        suffix = uuid.uuid4().hex[:12]
        self.env = {
            **{key: value for key, value in os.environ.items() if not key.startswith("C1_")},
            "C1_IDENTITY_MODE": "external",
            "C1_INSTANCE_ID": "m14c_" + suffix,
            "C1_INSTANCE_IRI_BASE": "urn:c1:external:" + suffix + ":",
            "C1_INITIALIZATION_FILE": str(directory / "initialization.json"),
            "C1_ISSUER": "http://127.0.0.1:29090",
            "C1_ISSUER_ALIAS": "external",
            "C1_AUDIENCE": "c1-api",
            "C1_OIDC_TOKEN_PROFILE": "hydra-jwt-v1",
            "C1_KNOWLEDGE_DATABASE": "m14c_knowledge_" + suffix,
            "C1_WORKFLOW_DATABASE": "m14c_workflow_" + suffix,
            "C1_TERMINUS_URL": "http://127.0.0.1:26363",
            "C1_FGA_URL": "http://127.0.0.1:28080",
            "C1_TERMINUS_PASSWORD": "m14c-synthetic-password",  # pragma: allowlist secret
            "C1_FGA_TOKEN": "m14c-synthetic-token",
            "C1_CURSOR_SECRET": "synthetic-cursor-secret-32-chars-min",  # pragma: allowlist secret
            "C1_BACKEND_TIMEOUT_S": "30",
            "C1_LOCK_PATH": str(directory / "writer.lock"),
            "C1_EXPLORER_ENABLED": "true",
            "C1_EXPLORER_ORIGIN": "http://127.0.0.1:29095",
            "C1_EXPLORER_CLIENT_ID": "c1-external-" + suffix,
            "C1_EXPLORER_CLIENT_SECRET": "synthetic-client-secret",  # pragma: allowlist secret
            "C1_EXPLORER_SCOPES": "openid offline_access",
            "C1_EXPLORER_AUDIENCE_PARAMETER": "audience",
        }
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "HF_TOKEN",
            "AZURE_OPENAI_API_KEY",
        ):
            self.env.pop(name, None)
        for name in ("C1_FGA_STORE", "C1_FGA_MODEL", "C1_CRASH_AFTER", "C1_ENABLE_PROBE_ROUTES"):
            self.env.pop(name, None)
        self.process: subprocess.Popen[bytes] | None = None
        self.ui: HydraIdentityUI | None = None
        self.client_options: dict[str, Any] = {}

    def operator(self, *arguments: str, expected: int = 0) -> dict[str, Any]:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from tests.integration.m14c.network_guard import install; "
                f"install(runtime={arguments[0] in {'oidc-check', 'dr-verify', 'dr-release'}}); "
                "from c1.admin.cli import main; raise SystemExit(main())",
                "application",
                *arguments,
            ],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            check=False,
        )
        assert result.returncode == expected, result.stdout.decode() + result.stderr.decode()
        value: dict[str, Any] = json.loads(result.stdout)
        return value

    def start(self) -> None:
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.post(
                "http://127.0.0.1:29091/admin/clients",
                json={
                    "client_id": self.env["C1_EXPLORER_CLIENT_ID"],
                    "client_secret": self.env["C1_EXPLORER_CLIENT_SECRET"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "openid offline_access",
                    "audience": ["c1-api"],
                    "token_endpoint_auth_method": "client_secret_basic",
                    "redirect_uris": [self.env["C1_EXPLORER_ORIGIN"] + "/explorer/callback"],
                    "post_logout_redirect_uris": [
                        self.env["C1_EXPLORER_ORIGIN"] + "/explorer/signed-out"
                    ],
                    **self.client_options,
                },
            )
            response.raise_for_status()
        first = self.operator("initialize", "--namespace-id", "hydra-fixture-namespace-v1")
        second = self.operator("initialize", "--namespace-id", "hydra-fixture-namespace-v1")
        assert first == second
        self.env.update(C1_FGA_STORE=first["fga_store"], C1_FGA_MODEL=first["fga_model"])
        self.ui = HydraIdentityUI("http://127.0.0.1:29091")
        self.ui.start()
        self.start_server()

    def operator_crash(self, boundary: str, *arguments: str) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from tests.integration.m14c.network_guard import install; install(runtime=True); "
                "from tests.integration.m14c.crash_hook import install; "
                f"install({boundary!r}); "
                "from c1.admin.cli import main; raise SystemExit(main())",
                "application",
                *arguments,
            ],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            check=False,
        )
        assert result.returncode == -signal.SIGKILL

    def start_server(self, boundary: str | None = None) -> None:
        hook = (
            f"from tests.integration.m14c.crash_hook import install; install({boundary!r}); "
            if boundary
            else ""
        )
        log = self.directory / "server.log"
        log.touch(mode=0o600, exist_ok=True)
        with log.open("ab") as stream:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from tests.integration.m14c.network_guard import install; "
                    "install(runtime=True); " + hook + "import uvicorn; uvicorn.main()",
                    "c1.web:from_env",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "29095",
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=self.env,
                stdout=stream,
                stderr=stream,
            )
        for _ in range(60):
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    client.get(self.env["C1_EXPLORER_ORIGIN"] + "/v1/readyz")
                return
            except httpx.HTTPError:
                if self.process.poll() is not None:
                    raise RuntimeError("external C1 process exited") from None
                time.sleep(0.5)
        raise RuntimeError("external C1 process did not start")

    def stop_server(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)

    def close(self) -> None:
        self.stop_server()
        if self.ui is not None:
            self.ui.close()

    def user_tokens(self, username: str, *, wrong_verifier: bool = False) -> dict[str, Any]:
        from c1.explorer.oidc import code_challenge

        verifier, state, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        callback = self.env["C1_EXPLORER_ORIGIN"] + "/explorer/callback"
        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.get(
                self.env["C1_ISSUER"] + "/oauth2/auth",
                params={
                    "client_id": self.env["C1_EXPLORER_CLIENT_ID"],
                    "response_type": "code",
                    "scope": "openid offline_access",
                    "audience": self.env["C1_AUDIENCE"],
                    "redirect_uri": callback,
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": code_challenge(verifier),
                    "code_challenge_method": "S256",
                },
            )
            for _ in range(15):
                location = response.headers.get("location", "")
                params = parse_qs(urlsplit(location).query)
                if "code" in params:
                    assert params["state"] == [state]
                    issued = client.post(
                        self.env["C1_ISSUER"] + "/oauth2/token",
                        auth=(
                            self.env["C1_EXPLORER_CLIENT_ID"],
                            self.env["C1_EXPLORER_CLIENT_SECRET"],
                        ),
                        data={
                            "grant_type": "authorization_code",
                            "code": params["code"][0],
                            "redirect_uri": callback,
                            "code_verifier": secrets.token_urlsafe(32)
                            if wrong_verifier
                            else verifier,
                        },
                    )
                    assert issued.status_code == (400 if wrong_verifier else 200)
                    result: dict[str, Any] = issued.json()
                    return result
                if location:
                    response = client.get(location)
                elif response.status_code == 200 and response.url.path == "/login":
                    response = client.post(
                        "http://127.0.0.1:29092/login",
                        data={
                            "csrf": client.cookies.get("hydra_login"),
                            "username": username,
                            "password": "synthetic-test-password",  # pragma: allowlist secret
                        },
                    )
                else:
                    raise RuntimeError("provider did not complete the code flow")
        raise RuntimeError("provider redirect limit exceeded")


@pytest.fixture
def external(tmp_path_factory: pytest.TempPathFactory) -> Iterator[External]:
    directory = tmp_path_factory.mktemp("external-oidc")
    directory.chmod(0o700)
    fixture = External(directory)
    try:
        fixture.start()
        yield fixture
    finally:
        fixture.close()
