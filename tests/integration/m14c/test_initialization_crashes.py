"""Actual SIGKILL and lost-response boundaries on real initialized backends."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.integration.m14c.conftest import ROOT, External


@pytest.mark.parametrize(
    "boundary",
    [
        "intent",
        "store_response",
        "store_checkpoint",
        "model_response",
        "model_checkpoint",
        "workflow_database_response",
        "workflow_schema_response",
        "workflow_checkpoint",
        "knowledge_database_response",
        "knowledge_schema_response",
        "core_marker_response",
        "core_checkpoint",
        "identity_binding_response",
        "initialization_complete",
    ],
)
def test_t03_initialization_sigkill_and_retry(tmp_path: Path, boundary: str) -> None:
    tmp_path.chmod(0o700)
    fixture = External(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.integration.m14c.network_guard import install; install(); "
            f"from tests.integration.m14c.crash_hook import install; install({boundary!r}); "
            "from c1.admin.cli import main; raise SystemExit(main())",
            "application",
            "initialize",
            "--namespace-id",
            "hydra-fixture-namespace-v1",
        ],
        cwd=ROOT,
        env=fixture.env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == -signal.SIGKILL
    before = json.loads((tmp_path / "initialization.json").read_text())
    owner = before["owner"]
    first = fixture.operator("initialize", "--namespace-id", "hydra-fixture-namespace-v1")
    second = fixture.operator("initialize", "--namespace-id", "hydra-fixture-namespace-v1")
    assert first == second
    after = json.loads((tmp_path / "initialization.json").read_text())
    assert after["owner"] == owner
    assert after["state"] == "awaiting_enrollment" and "administrator" not in after
    with httpx.Client(trust_env=False, timeout=30) as client:
        stores = []
        continuation = ""
        for _ in range(100):
            page = client.get(
                "http://127.0.0.1:28080/stores",
                headers={"Authorization": "Bearer m14c-synthetic-token"},
                params={"page_size": 100, "continuation_token": continuation},
            ).json()
            stores.extend(page["stores"])
            continuation = page.get("continuation_token", "")
            if not continuation:
                break
        else:
            raise AssertionError("fixture store inventory did not finish")
        assert len([store for store in stores if store["name"] == owner]) == 1
        tuples = client.post(
            "http://127.0.0.1:28080/stores/" + after["fga_store"] + "/read",
            headers={"Authorization": "Bearer m14c-synthetic-token"},
            json={"consistency": "HIGHER_CONSISTENCY"},
        ).json()["tuples"]
        assert not tuples
