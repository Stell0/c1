"""Operator schemas, sanitized failures, and recovery manifest integrity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from c1.admin.cli import main
from c1.admin.initialization import InitializationError, save
from c1.admin.recovery import ARTIFACTS, digest, verify_manifest


def test_operator_contract_has_versioned_schemas_and_no_qualification_claim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["application", "contract"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["contract_version"] == 1
    assert {"initialize", "enrollment_approval", "namespace_evidence", "operator_result"} <= (
        result["schemas"].keys()
    )
    assert result["capabilities"]["production_qualified"] is False


def test_argument_errors_are_machine_readable_and_do_not_echo_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["application", "enrollment-approve", "--expires-in", "sensitive-input-value"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "sensitive-input-value" not in captured.out + captured.err
    assert json.loads(captured.out)["error"] == "invalid_arguments"


def test_external_state_reports_empty_before_backend_ids_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("C1_INITIALIZATION_FILE", str(tmp_path / "initialization.json"))
    assert main(["application", "state"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "contract_version": 1,
        "state": "empty",
        "ready": False,
    }


def test_manifest_requires_exact_application_owned_artifacts_and_integrity(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    for name in ARTIFACTS:
        path = tmp_path / name
        path.write_bytes(b"synthetic-owned-state")
        path.chmod(0o600)
    manifest: dict[str, Any] = {
        "contract_version": 1,
        "manifest_version": 2,
        "type": "external-full",
        "created_at": "2026-10-09T00:00:00+00:00",
        "operator": "synthetic-operator",
        "identity": {},
        "namespace_id": "synthetic-namespace",
        "fga_store": "store",
        "fga_model": "model",
        "model_sha256": "0" * 64,
        "knowledge_head": "knowledge-head",
        "workflow_head": "workflow-head",
        "profiles": {},
        "security_sha256": "0" * 64,
        "files": {name: digest(tmp_path / name) for name in ARTIFACTS},
    }
    save(tmp_path / "manifest.json", manifest)
    assert verify_manifest(tmp_path)["type"] == "external-full"
    extra = {**manifest, "files": {**manifest["files"], "keycloak.pgdump": "0" * 64}}
    save(tmp_path / "manifest.json", extra)
    with pytest.raises(InitializationError, match="incomplete"):
        verify_manifest(tmp_path)
    save(tmp_path / "manifest.json", manifest)
    (tmp_path / ARTIFACTS[0]).write_bytes(b"corruption")
    with pytest.raises(InitializationError, match="integrity"):
        verify_manifest(tmp_path)


def test_backup_artifacts_cannot_be_symlinks_or_public(tmp_path: Path) -> None:
    artifact = tmp_path / "snapshot"
    artifact.write_bytes(b"synthetic")
    artifact.chmod(0o644)
    with pytest.raises(InitializationError, match="unsafe"):
        digest(artifact)
    artifact.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(artifact)
    with pytest.raises(InitializationError, match="unsafe"):
        digest(link)
