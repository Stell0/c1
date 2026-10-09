"""Application-only cold snapshots restored into fresh real backend volumes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from c1.admin.host import Deployment
from c1.admin.initialization import save
from tests.integration.m14c.conftest import ROOT, External
from tests.integration.m14c.test_external_browser import (
    test_t01_t02_t04_t05_t07_t09_external_browser as seed_workflow,
)


def _ready(url: str) -> None:
    with httpx.Client(trust_env=False, timeout=5) as client:
        for _ in range(90):
            try:
                response = client.get(
                    url,
                    auth=("admin", "m14c-synthetic-password")
                    if url.endswith("/api/info")
                    else None,
                )
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise RuntimeError("isolated restored backend did not become ready")


def test_t12_t13_external_application_only_backup_and_guarded_restore(
    external: External,
    tmp_path: Path,
) -> None:
    seed_workflow(external)
    tokens = external.user_tokens("approved")
    external.stop_server()
    source = Deployment(
        ROOT / "deployment/external-test", "c1-m14c-external", {"C1_ENGINE": "docker"}
    )
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    source.run(["docker", "stop", source.container("terminusdb")])
    try:
        source.export_volume("c1-m14c-external_terminus-data", backup / "terminusdb-storage.tar")
    finally:
        source.run(["docker", "start", source.container("terminusdb")])
    _ready("http://127.0.0.1:26363/api/info")
    # /api/info is a process probe; warm and verify the actual restored
    # databases before asking the operator to inspect a consistent snapshot.
    external.operator("state")
    dump = source.run(
        [
            "docker",
            "exec",
            source.container("postgres"),
            "pg_dump",
            "-U",
            "openfga",
            "--format=custom",
            "openfga",
        ]
    ).stdout
    (backup / "openfga.pgdump").write_bytes(dump)
    (backup / "openfga.pgdump").chmod(0o600)
    external.operator_crash(
        "backup_manifest_response",
        "backup-manifest",
        "--directory",
        str(backup),
        "--operator",
        "synthetic-recovery-operator",
    )
    assert (
        external.operator(
            "backup-manifest",
            "--directory",
            str(backup),
            "--operator",
            "synthetic-recovery-operator",
            expected=2,
        )["error"]
        == "backup_manifest_exists"
    )
    manifest = json.loads((backup / "manifest.json").read_text())
    assert set(manifest["files"]) == {
        "terminusdb-storage.tar",
        "openfga.pgdump",
        "initialization.json",
    }
    assert "keycloak" not in manifest["files"]
    assert manifest["manifest_version"] == 2
    directory = tmp_path / "restored"
    directory.mkdir(mode=0o700)
    shutil.copy2(backup / "initialization.json", directory / "initialization.json")
    recovered = External(directory)
    recovered.env = {
        **external.env,
        "C1_INITIALIZATION_FILE": str(directory / "initialization.json"),
        "C1_LOCK_PATH": str(directory / "writer.lock"),
        "C1_TERMINUS_URL": "http://127.0.0.1:27363",
        "C1_FGA_URL": "http://127.0.0.1:28081",
    }
    target_env = {
        **os.environ,
        "C1_EXTERNAL_TERMINUS_PASSWORD": "m14c-synthetic-password",  # pragma: allowlist secret
        "C1_EXTERNAL_PG_PASSWORD": "m14c-synthetic-pg-password",  # pragma: allowlist secret
        "C1_EXTERNAL_FGA_TOKEN": "m14c-synthetic-token",
        "C1_EXTERNAL_HYDRA_SECRET": "m14c-synthetic-hydra-secret-value",  # pragma: allowlist secret
        "C1_EXTERNAL_TERMINUS_PORT": "27363",
        "C1_EXTERNAL_FGA_PORT": "28081",
    }
    compose = [
        os.environ.get("C1_EXTERNAL_COMPOSE", "/tmp/c1-m14c-tools/docker-compose"),
        "-p",
        "c1-m14c-recovery",
        "-f",
        str(ROOT / "deployment/external-test/compose.yaml"),
    ]
    target = Deployment(
        ROOT / "deployment/external-test", "c1-m14c-recovery", {**target_env, "C1_ENGINE": "docker"}
    )
    try:
        existing = target.run(["docker", "volume", "ls", "--format", "{{.Name}}"])
        assert not any(
            name.startswith("c1-m14c-recovery_") for name in existing.stdout.decode().split()
        )
        target.run(["docker", "volume", "create", "c1-m14c-recovery_terminus-data"])
        target.import_volume("c1-m14c-recovery_terminus-data", backup / "terminusdb-storage.tar")
        subprocess.run(
            [*compose, "up", "-d", "postgres", "terminusdb"],
            env=target_env,
            capture_output=True,
            check=True,
        )
        _ready("http://127.0.0.1:27363/api/info")
        for _ in range(30):
            probe = target.run(
                ["docker", "exec", target.container("postgres"), "pg_isready", "-U", "openfga"],
                check=False,
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        target.run(
            [
                "docker",
                "exec",
                "-i",
                target.container("postgres"),
                "pg_restore",
                "-U",
                "openfga",
                "-d",
                "openfga",
                "--clean",
                "--if-exists",
                "--no-owner",
            ],
            input=(backup / "openfga.pgdump").read_bytes(),
        )
        subprocess.run(
            [*compose, "up", "-d", "openfga-migrate", "openfga"],
            env=target_env,
            capture_output=True,
            check=True,
        )
        _ready("http://127.0.0.1:28081/healthz")
        # Transport failures are checked against real restored backends before
        # a valid guard is accepted. Never publish a target on command failure.
        for altered, error in [
            ({**manifest, "files": {}}, "incomplete_backup_manifest"),
            ({**manifest, "manifest_version": 99}, "incompatible_backup_manifest"),
        ]:
            save(backup / "manifest.json", altered)
            assert (
                recovered.operator(
                    "restore-validate",
                    "--directory",
                    str(backup),
                    "--operator",
                    "synthetic-recovery-operator",
                    expected=2,
                )["error"]
                == error
            )
        save(backup / "manifest.json", manifest)
        artifact = backup / "openfga.pgdump"
        length = artifact.stat().st_size
        with artifact.open("ab") as stream:
            stream.write(b"corruption")
        assert (
            recovered.operator(
                "restore-validate",
                "--directory",
                str(backup),
                "--operator",
                "synthetic-recovery-operator",
                expected=2,
            )["error"]
            == "backup_integrity_failure"
        )
        with artifact.open("r+b") as stream:
            stream.truncate(length)
        recovered.operator_crash(
            "restore_guard_response",
            "restore-validate",
            "--directory",
            str(backup),
            "--operator",
            "synthetic-recovery-operator",
        )
        validated = recovered.operator(
            "restore-validate",
            "--directory",
            str(backup),
            "--operator",
            "synthetic-recovery-operator",
        )
        assert validated["released"] is False
        recovered.env["C1_BACKEND_TIMEOUT_S"] = "2"
        target.run(["docker", "pause", target.container("openfga")])
        try:
            recovered.start_server()
        finally:
            target.run(["docker", "unpause", target.container("openfga")])
        recovered.env["C1_BACKEND_TIMEOUT_S"] = "30"
        with httpx.Client(trust_env=False, timeout=30) as client:
            assert client.get(external.env["C1_EXPLORER_ORIGIN"] + "/v1/readyz").status_code == 503
        recovered.stop_server()
        evidence = directory / "continuity.json"
        proof = {
            "contract_version": 1,
            "issuer": recovered.env["C1_ISSUER"],
            "namespace_id": "hydra-fixture-namespace-v1",
            "instance_id": recovered.env["C1_INSTANCE_ID"],
            "client_id": recovered.env["C1_EXPLORER_CLIENT_ID"],
            "subject": "external|approved",
            "operator": "synthetic-recovery-operator",
            "continuity_verified": True,
            "verified_at": time.time(),
            "evidence_sha256": hashlib.sha256(
                b"independently inspected fixture continuity"
            ).hexdigest(),
        }
        token_file = directory / "continuity-token"
        token_file.write_text(tokens["access_token"])
        token_file.chmod(0o600)
        save(evidence, {**proof, "namespace_id": "recreated-namespace"})
        assert recovered.operator(
            "dr-verify",
            "--namespace-evidence",
            str(evidence),
            "--continuity-token-file",
            str(token_file),
            expected=2,
        )["error"] == ("namespace_continuity_unverified")
        save(evidence, proof)
        save(evidence, {**proof, "verified_at": time.time() - 3601})
        assert (
            recovered.operator(
                "dr-verify",
                "--namespace-evidence",
                str(evidence),
                "--continuity-token-file",
                str(token_file),
                expected=2,
            )["error"]
            == "namespace_continuity_unverified"
        )
        save(evidence, proof)
        recovered.env["C1_BACKEND_TIMEOUT_S"] = "2"
        source.run(["docker", "pause", "c1-m14c-external-hydra-1"])
        try:
            assert (
                recovered.operator(
                    "dr-verify",
                    "--namespace-evidence",
                    str(evidence),
                    "--continuity-token-file",
                    str(token_file),
                    expected=4,
                )["error"]
                == "identity_service_unavailable"
            )
        finally:
            source.run(["docker", "unpause", "c1-m14c-external-hydra-1"])
        recovered.env["C1_BACKEND_TIMEOUT_S"] = "30"
        recovered.operator_crash(
            "recovery_verify_response",
            "dr-verify",
            "--namespace-evidence",
            str(evidence),
            "--continuity-token-file",
            str(token_file),
        )
        verified = recovered.operator(
            "dr-verify",
            "--namespace-evidence",
            str(evidence),
            "--continuity-token-file",
            str(token_file),
        )
        assert verified["consistent"] is True
        # Membership/grant changes can leave binding consistency true. The
        # exact authorization snapshot must still invalidate release.
        with httpx.Client(trust_env=False, timeout=30) as client:
            store = recovered.env["C1_FGA_URL"] + "/stores/" + recovered.env["C1_FGA_STORE"]
            headers = {"Authorization": "Bearer m14c-synthetic-token"}
            key = {
                "user": "user:external.~ZXh0ZXJuYWx8YXBwcm92ZWQ",
                "relation": "operator",
                "object": "instance:" + recovered.env["C1_INSTANCE_ID"],
            }
            changed = client.post(
                store + "/write",
                headers=headers,
                json={
                    "authorization_model_id": recovered.env["C1_FGA_MODEL"],
                    "writes": {"tuple_keys": [key]},
                },
            )
            assert changed.status_code == 200
            stale = recovered.operator(
                "dr-release",
                "--namespace-evidence",
                str(evidence),
                "--continuity-token-file",
                str(token_file),
                "--accept-security-as-of",
                manifest["created_at"],
                "--operator",
                "synthetic-recovery-operator",
                "--reason",
                "stale check",
                expected=2,
            )
            assert stale["error"] == "restore_verification_stale"
            restored = client.post(
                store + "/write",
                headers=headers,
                json={
                    "authorization_model_id": recovered.env["C1_FGA_MODEL"],
                    "deletes": {"tuple_keys": [key]},
                },
            )
            assert restored.status_code == 200
        recovered.operator(
            "dr-verify",
            "--namespace-evidence",
            str(evidence),
            "--continuity-token-file",
            str(token_file),
        )
        recovered.operator_crash(
            "recovery_release_response",
            "dr-release",
            "--namespace-evidence",
            str(evidence),
            "--continuity-token-file",
            str(token_file),
            "--accept-security-as-of",
            manifest["created_at"],
            "--operator",
            "synthetic-recovery-operator",
            "--reason",
            "fixture recovery",
        )
        state = recovered.operator("state")
        assert state["restore_guarded"] is False
        guards = [entry for entry in state["restore_records"] if entry.get("type") == "guard"]
        assert len(guards) == 1
        assert guards[0]["released"] is True
        recovered.start_server()
        with httpx.Client(
            base_url=external.env["C1_EXPLORER_ORIGIN"], trust_env=False, timeout=60
        ) as client:
            assert client.get("/v1/readyz").status_code == 200
            response = client.get(
                "/v1/entities",
                headers={
                    "Authorization": "Bearer " + tokens["access_token"],
                },
            )
            assert response.status_code == 200 and "External reviewed modification" in response.text
        recovered.stop_server()
        assert recovered.operator("consistency")["consistent"] is True
        assert recovered.operator("optimize")["knowledge"]["head_unchanged"] is True
    finally:
        recovered.close()
        subprocess.run(
            [*compose, "down", "--volumes"], env=target_env, capture_output=True, check=False
        )
