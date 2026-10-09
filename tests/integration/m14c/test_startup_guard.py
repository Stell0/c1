"""Identity configuration cannot bypass guards after interrupted startup."""

from __future__ import annotations

import subprocess

import httpx

from tests.integration.m14c.conftest import External
from tests.integration.m14c.test_failures import enroll


def test_t04_t10_startup_outage_cannot_select_legacy_identity_mode(external: External) -> None:
    headers = enroll(external)
    external.stop_server()
    original = dict(external.env)
    external.env["C1_IDENTITY_MODE"] = "reference"
    external.env.pop("C1_INITIALIZATION_FILE")
    external.env["C1_BACKEND_TIMEOUT_S"] = "2"
    container = "c1-m14c-external-openfga-1"
    subprocess.run(["docker", "pause", container], capture_output=True, check=True)
    try:
        external.start_server()
    finally:
        subprocess.run(["docker", "unpause", container], capture_output=True, check=True)
    with httpx.Client(trust_env=False, timeout=30) as client:
        origin = external.env["C1_EXPLORER_ORIGIN"]
        assert client.get(origin + "/v1/readyz").status_code == 503
        assert client.get(origin + "/v1/access-scopes", headers=headers).status_code == 503
    external.stop_server()
    external.env = original
    external.start_server()
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert client.get(external.env["C1_EXPLORER_ORIGIN"] + "/v1/readyz").status_code == 200
