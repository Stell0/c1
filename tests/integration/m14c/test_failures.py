"""Live provider rotation/outages, instance isolation and fail-closed setup."""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from playwright.sync_api import Request, sync_playwright

from tests.integration.m14c.conftest import External


def enroll(fixture: External) -> dict[str, str]:
    fixture.operator(
        "enrollment-approve",
        "--issuer",
        fixture.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    tokens = fixture.user_tokens("approved")
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert (
            client.post(
                fixture.env["C1_EXPLORER_ORIGIN"] + "/v1/setup/confirm",
                headers=headers,
                json={},
            ).status_code
            == 200
        )
    return headers


def test_t02_concurrent_confirmation_and_t04_populated_restart(external: External) -> None:
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    headers = {"Authorization": "Bearer " + external.user_tokens("approved")["access_token"]}
    origin = external.env["C1_EXPLORER_ORIGIN"]

    def confirm() -> int:
        with httpx.Client(trust_env=False, timeout=30) as client:
            return client.post(origin + "/v1/setup/confirm", headers=headers, json={}).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: confirm(), range(4)))
    assert 200 in statuses and all(status in {200, 403, 409, 503} for status in statuses)
    with httpx.Client(trust_env=False, timeout=30) as client:
        created = client.post(
            origin + "/v1/access-scopes",
            headers=headers,
            json={"label": "Persisted scope"},
        )
        assert created.status_code == 201
        scope = created.json()["id"]
    before = json.loads((external.directory / "initialization.json").read_text())
    external.stop_server()
    external.operator("initialize", "--namespace-id", "hydra-fixture-namespace-v1")
    assert json.loads((external.directory / "initialization.json").read_text()) == before
    # Runtime tuning is allowed; identity/client registration is immutable.
    external.env["C1_BACKEND_TIMEOUT_S"] = "20"
    external.start_server()
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert client.get(origin + "/v1/readyz").status_code == 200
        assert scope in client.get(origin + "/v1/access-scopes", headers=headers).text
    changed = dict(external.env)
    external.env["C1_ISSUER_ALIAS"] = "replacement"
    assert external.operator("state", expected=2)["error"] == "identity_configuration_changed"
    external.env = changed


def test_t06_browser_state_and_pkce_fail_closed(external: External) -> None:
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    origin = external.env["C1_EXPLORER_ORIGIN"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for field in ("state", "code"):
            page = browser.new_page()
            states: list[str] = []

            def capture(request: Request, states: list[str] = states) -> None:
                query = parse_qs(urlsplit(request.url).query)
                if urlsplit(request.url).path == "/oauth2/auth" and "state" in query:
                    states.append(query["state"][0])

            page.on("request", capture)
            page.goto(origin + "/explorer/login")
            assert states
            response = page.goto(
                origin
                + "/explorer/callback?"
                + urlencode(
                    {
                        "code": "unissued-authorization-code",
                        "state": "wrong-state" if field == "state" else states[0],
                    }
                )
            )
            assert response is not None and response.status == 400
            page.get_by_text("Sign-in failed. Start again.", exact=True).wait_for()
            assert not any(c["name"] == "__Host-c1_session" for c in page.context.cookies())
            page.close()
        browser.close()
    with httpx.Client(trust_env=False) as client:
        assert client.get(origin + "/v1/readyz").status_code == 503
    assert external.user_tokens("approved", wrong_verifier=True)["error"] == "invalid_grant"


def test_t10_real_key_rotation_and_outages(external: External) -> None:
    headers = enroll(external)
    external.stop_server()
    external.env["C1_BACKEND_TIMEOUT_S"] = "2"
    external.start_server()
    origin = external.env["C1_EXPLORER_ORIGIN"]
    with httpx.Client(trust_env=False, timeout=10) as client:
        assert client.get(origin + "/v1/whoami", headers=headers).status_code == 200
        response = client.post(
            origin + "/v1/access-scopes", headers=headers, json={"label": "Outage scope"}
        )
        assert response.status_code == 201
        scope = response.json()["id"]
        assert scope in client.get(origin + "/v1/access-scopes", headers=headers).text
        for container in ("c1-m14c-external-hydra-1", "c1-m14c-external-openfga-1"):
            subprocess.run(["docker", "pause", container], capture_output=True, check=True)
            try:
                assert client.get(origin + "/v1/readyz").status_code == 503
                if "openfga" in container:
                    unavailable = client.get(origin + "/v1/access-scopes", headers=headers)
                    assert unavailable.status_code in {200, 403, 503}
                    assert scope not in unavailable.text and "Outage scope" not in unavailable.text
                else:
                    # A known cached signing key still validates an unexpired
                    # token; an unknown key cannot be fetched while offline.
                    parts = headers["Authorization"].removeprefix("Bearer ").split(".")
                    import base64

                    parts[0] = (
                        base64.urlsafe_b64encode(
                            json.dumps({"kid": "unknown", "alg": "RS256", "typ": "JWT"}).encode()
                        )
                        .decode()
                        .rstrip("=")
                    )
                    unknown = {"Authorization": "Bearer " + ".".join(parts)}
                    assert client.get(origin + "/v1/whoami", headers=unknown).status_code == 401
            finally:
                subprocess.run(["docker", "unpause", container], capture_output=True, check=True)
            assert client.get(origin + "/v1/readyz").status_code == 200
        # Supervisor rotates the provider's key without replacing its namespace.
        old = jwt.get_unverified_header(headers["Authorization"].removeprefix("Bearer "))["kid"]
        response = client.post(
            "http://127.0.0.1:29091/admin/keys/hydra.jwt.access-token",
            json={"alg": "RS256", "kid": "m14c-rotation-" + str(time.time_ns()), "use": "sig"},
        )
        assert response.status_code == 201
        response = client.delete("http://127.0.0.1:29091/admin/keys/hydra.jwt.access-token/" + old)
        assert response.status_code == 204
    fresh = external.user_tokens("approved")["access_token"]
    assert jwt.get_unverified_header(fresh)["kid"] != old
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert (
            client.get(
                origin + "/v1/whoami", headers={"Authorization": "Bearer " + fresh}
            ).status_code
            == 200
        )
        assert client.get(origin + "/v1/readyz").status_code == 200
    assert external.operator("state")["state"] == "complete"


def test_t10_distinct_instances_do_not_inherit_grants(external: External, tmp_path: Path) -> None:
    headers = enroll(external)
    tmp_path.chmod(0o700)
    second = External(tmp_path)
    second.env["C1_ISSUER_ALIAS"] = "other_namespace"
    first = second.operator("initialize", "--namespace-id", "different-namespace")
    assert first["fga_store"] != external.env["C1_FGA_STORE"]
    assert first["fga_model"] != external.env["C1_FGA_MODEL"]
    external.stop_server()
    second.env.update(C1_FGA_STORE=first["fga_store"], C1_FGA_MODEL=first["fga_model"])
    try:
        second.start_server()
        with httpx.Client(trust_env=False, timeout=30) as client:
            origin = second.env["C1_EXPLORER_ORIGIN"]
            assert client.get(origin + "/v1/readyz").status_code == 503
            assert (
                client.post(origin + "/v1/setup/confirm", headers=headers, json={}).status_code
                == 403
            )
            assert client.get(origin + "/v1/access-scopes", headers=headers).status_code == 503
    finally:
        second.close()
