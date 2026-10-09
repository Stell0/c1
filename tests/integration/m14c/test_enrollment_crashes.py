"""Actual process death at enrollment boundaries never grants another identity."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from c1.authorization.principal import Principal
from tests.integration.m14c.conftest import ROOT, External


@pytest.mark.parametrize(
    "boundary",
    [
        "approval_checkpoint",
        "enrollment_intent",
        "enrollment_access_grant",
        "enrollment_schema_grant",
        "enrollment_audit_response",
        "enrollment_complete",
    ],
)
def test_t03_enrollment_sigkill_preserves_exact_approval(tmp_path: Path, boundary: str) -> None:
    tmp_path.chmod(0o700)
    fixture = External(tmp_path)
    try:
        fixture.start()
        if boundary == "approval_checkpoint":
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from tests.integration.m14c.network_guard import install; install(); "
                    "from tests.integration.m14c.crash_hook import install; "
                    "install('approval_checkpoint'); "
                    "from c1.admin.cli import main; raise SystemExit(main())",
                    "application",
                    "enrollment-approve",
                    "--issuer",
                    fixture.env["C1_ISSUER"],
                    "--subject",
                    "external|approved",
                    "--operator",
                    "synthetic-operator",
                ],
                env=fixture.env,
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            assert result.returncode == -signal.SIGKILL
        else:
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
        other = fixture.user_tokens("other")
        fixture.stop_server()
        if boundary != "approval_checkpoint":
            fixture.start_server(boundary)
            with httpx.Client(trust_env=False, timeout=60) as client:
                try:
                    client.post(
                        fixture.env["C1_EXPLORER_ORIGIN"] + "/v1/setup/confirm",
                        headers={"Authorization": "Bearer " + tokens["access_token"]},
                        json={},
                    )
                except httpx.HTTPError:
                    pass
            assert fixture.process is not None
            assert fixture.process.wait(timeout=15) == -signal.SIGKILL
        fixture.start_server()
        state = json.loads((tmp_path / "initialization.json").read_text())
        with httpx.Client(
            base_url=fixture.env["C1_EXPLORER_ORIGIN"], trust_env=False, timeout=60
        ) as client:
            if state["state"] != "complete":
                assert client.get("/v1/readyz").status_code == 503
                wrong = client.post(
                    "/v1/setup/confirm",
                    headers={"Authorization": "Bearer " + other["access_token"]},
                    json={},
                )
                assert wrong.status_code == 403
                confirmed = client.post(
                    "/v1/setup/confirm",
                    headers={"Authorization": "Bearer " + tokens["access_token"]},
                    json={},
                )
                assert confirmed.status_code == 200
            assert client.get("/v1/readyz").status_code == 200
            assert (
                client.post(
                    "/v1/access-scopes",
                    json={"label": "Denied"},
                    headers={"Authorization": "Bearer " + other["access_token"]},
                ).status_code
                == 403
            )
        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.post(
                fixture.env["C1_FGA_URL"] + "/stores/" + fixture.env["C1_FGA_STORE"] + "/read",
                headers={"Authorization": "Bearer m14c-synthetic-token"},
                json={"consistency": "HIGHER_CONSISTENCY"},
            )
            keys = [entry["key"] for entry in response.json()["tuples"]]
            approved = Principal("external", "external|approved", "human").id
            assert len(keys) == 2 and {key["user"] for key in keys} == {approved}
            assert {key["relation"] for key in keys} == {"access_admin", "schema_admin"}
    finally:
        fixture.close()
