"""External-provider backup manifests and explicit identity-continuity proof.

The supervisor transports quiesced database snapshots. This module verifies
application state and integrity without owning the external identity service.
"""

from __future__ import annotations

import hashlib
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from c1.admin.contracts import ExternalBackupManifest, NamespaceEvidence
from c1.admin.initialization import InitializationError, checked, load, save
from c1.admin.internal import _consistency, _guard
from c1.authorization.fga import _snake_keys, model_definition
from c1.authorization.tokens import AuthenticationError
from c1.config import ExplorerSettings
from c1.runtime import Runtime
from c1.storage.schema import assert_installed_profiles

ARTIFACTS = ("terminusdb-storage.tar", "openfga.pgdump", "initialization.json")


async def immutable_identity(runtime: Runtime) -> dict[str, Any]:
    state = checked(runtime.settings)
    binding = await runtime.journal.get("Restore", "application-identity")
    if (
        state is None
        or binding is None
        or any(
            state.get(key) != binding.get(key)
            for key in ("identity", "namespace_id", "owner", "fga_store", "fga_model")
        )
    ):
        raise InitializationError("identity_configuration_changed")
    return state


async def compatible_model(runtime: Runtime) -> None:
    from c1.admin.initialization import _model_shape

    body = await runtime.fga._request(
        "GET", runtime.fga._path + "/authorization-models/" + runtime.settings.fga_model
    )
    actual = body.get("authorization_model", {})
    if _model_shape(_snake_keys({k: v for k, v in actual.items() if k != "id"})) != (
        _model_shape(_snake_keys(model_definition()))
    ):
        raise InitializationError("incompatible_authorization_model")


def digest(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise InitializationError("unsafe_backup_artifact")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


async def manifest(runtime: Runtime, directory: Path, operator: str) -> dict[str, Any]:
    from argparse import Namespace

    from c1.admin.internal import state as application_state

    if runtime.settings.identity_mode != "external":
        raise InitializationError("external_identity_required")
    state = await immutable_identity(runtime)
    if state.get("state") != "complete":
        raise InitializationError("enrollment_incomplete")
    status = await application_state(Namespace())
    consistent = await _consistency(runtime)
    if not consistent["consistent"] or status["restore_guarded"]:
        raise InitializationError("backup_state_inconsistent")
    await assert_installed_profiles(runtime.knowledge, runtime.registry)
    await compatible_model(runtime)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise InitializationError("unsafe_backup_directory")
    if (directory / "manifest.json").exists():
        raise InitializationError("backup_manifest_exists")
    save(directory / "initialization.json", state)
    value = {
        "contract_version": 1,
        "manifest_version": 2,
        "type": "external-full",
        "created_at": datetime.now(UTC).isoformat(),
        "operator": operator,
        "identity": state["identity"],
        "namespace_id": state["namespace_id"],
        "fga_store": runtime.settings.fga_store,
        "fga_model": runtime.settings.fga_model,
        "model_sha256": state["model_sha256"],
        "knowledge_head": status["knowledge_head"],
        "workflow_head": status["workflow_head"],
        "profiles": status["profiles"],
        "security_sha256": consistent["security_sha256"],
        "files": {name: digest(directory / name) for name in ARTIFACTS},
    }
    save(directory / "manifest.json", value)
    return {"manifest_sha256": digest(directory / "manifest.json"), "manifest_version": 2}


def verify_manifest(directory: Path) -> dict[str, Any]:
    value = load(directory / "manifest.json")
    if value.get("manifest_version") != 2 or value.get("type") != "external-full":
        raise InitializationError("incompatible_backup_manifest")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(ARTIFACTS):
        raise InitializationError("incomplete_backup_manifest")
    try:
        ExternalBackupManifest.model_validate(value)
        recorded = datetime.fromisoformat(value["created_at"])
        if recorded.tzinfo is None or recorded.timestamp() > time.time() + 30:
            raise ValueError("invalid snapshot time")
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise InitializationError("incomplete_backup_manifest") from None
    for name in ARTIFACTS:
        if digest(directory / name) != files[name]:
            raise InitializationError("backup_integrity_failure")
    return value


async def restore_validate(runtime: Runtime, directory: Path, operator: str) -> dict[str, Any]:
    value = verify_manifest(directory)
    state = await immutable_identity(runtime)
    if any(
        state.get(name) != value.get(name)
        for name in ("identity", "namespace_id", "fga_store", "fga_model", "model_sha256")
    ):
        raise InitializationError("restored_identity_mismatch")
    key = "external-dr-" + digest(directory / "manifest.json")
    existing = await runtime.journal.get("Restore", key)
    if existing is not None and existing.get("released"):
        raise InitializationError("restore_already_released")
    guards = [
        g
        for g in await runtime.journal.list("Restore")
        if g.get("type") == "guard" and g.get("released") is not True
    ]
    if any(g.get("id") != key for g in guards):
        raise InitializationError("ambiguous_restore_guard")
    if existing is None:
        # Establish the guard before backend compatibility verification.
        await runtime.journal.save_many(
            [
                (
                    "Restore",
                    key,
                    {
                        "id": key,
                        "type": "guard",
                        "released": False,
                        "manifest_sha256": digest(directory / "manifest.json"),
                        "backup_created_at": value["created_at"],
                        "operator": operator,
                        "recorded_at": datetime.now(UTC).isoformat(),
                        "restored_workflow_head": await runtime.journal.head(),
                    },
                )
            ]
        )
    guard = await runtime.journal.get("Restore", key)
    if (
        await runtime.knowledge.head() != value["knowledge_head"]
        or guard is None
        or guard.get("restored_workflow_head") != value["workflow_head"]
    ):
        raise InitializationError("restored_knowledge_mismatch")
    await assert_installed_profiles(runtime.knowledge, runtime.registry)
    security = await _consistency(runtime)
    if (
        not await runtime.fga.ready()
        or not security["consistent"]
        or security["security_sha256"] != value["security_sha256"]
    ):
        raise InitializationError("restored_security_inconsistent")
    await compatible_model(runtime)
    state["backend_origins"] = {
        "terminus_url": runtime.settings.terminus_url,
        "fga_url": runtime.settings.fga_url,
    }
    assert runtime.settings.initialization_file is not None
    save(runtime.settings.initialization_file, state)
    return {"guard": key, "namespace_verified": False, "released": False}


async def namespace_proof(runtime: Runtime, evidence: Path, token_file: Path) -> dict[str, Any]:
    state = await immutable_identity(runtime)
    document = load(evidence)
    NamespaceEvidence.model_validate(document)
    explorer = ExplorerSettings.from_env()
    if explorer is None:
        raise InitializationError("explorer_registration_required")
    expected = {
        "issuer": runtime.settings.issuer,
        "namespace_id": state["namespace_id"],
        "instance_id": runtime.settings.instance_id,
        "client_id": explorer.client_id,
        "subject": state.get("approval", {}).get("subject"),
    }
    if any(document.get(k) != v for k, v in expected.items()) or not expected["subject"]:
        raise InitializationError("namespace_continuity_unverified")
    if (
        document.get("continuity_verified") is not True
        or not isinstance(document.get("operator"), str)
        or not document["operator"]
        or not isinstance(document.get("evidence_sha256"), str)
        or len(document["evidence_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in document["evidence_sha256"])
        or type(document.get("verified_at")) not in (int, float)
        or not -30 <= time.time() - document["verified_at"] <= 3600
    ):
        raise InitializationError("namespace_continuity_unverified")
    # A fresh token proves current authenticated subject continuity; the
    # protected operator attestation additionally verifies namespace ownership
    # and pairwise-client continuity, which issuer text cannot establish.
    digest(token_file)
    if not await runtime.tokens.ready():
        raise InitializationError("identity_service_unavailable")
    try:
        principal = await runtime.tokens.authenticate(token_file.read_text().strip())
    except AuthenticationError:
        raise InitializationError("invalid_continuity_token") from None
    if principal.kind != "human" or principal.subject != expected["subject"]:
        raise InitializationError("namespace_subject_mismatch")
    return {
        "evidence_sha256": digest(evidence),
        "verified_at": document["verified_at"],
        "namespace_id": state["namespace_id"],
        "operator": document["operator"],
    }


async def verify(runtime: Runtime, evidence: Path, token_file: Path) -> dict[str, Any]:
    proof = await namespace_proof(runtime, evidence, token_file)
    guard = await _guard(runtime.journal)
    result = await _consistency(runtime)
    if not result["consistent"]:
        raise InitializationError("restored_security_inconsistent")
    await assert_installed_profiles(runtime.knowledge, runtime.registry)
    if not await runtime.fga.ready():
        raise InitializationError("incompatible_authorization_model")
    guard["verify"] = {
        **result,
        "knowledge_head": await runtime.knowledge.head(),
        "namespace": proof,
        "verified_at": time.time(),
    }
    await runtime.journal.save_many([("Restore", guard["id"], guard)])
    return result


async def release_check(
    runtime: Runtime, evidence: Path, token_file: Path, accepted_at: str
) -> None:
    proof = await namespace_proof(runtime, evidence, token_file)
    guard = await _guard(runtime.journal)
    verified = guard.get("verify", {})
    result = await _consistency(runtime)
    if (
        not verified.get("consistent")
        or not result["consistent"]
        or time.time() - verified.get("verified_at", 0) > 300
        or verified.get("namespace") != proof
        or verified.get("security_sha256") != result["security_sha256"]
        or verified.get("knowledge_head") != await runtime.knowledge.head()
        or accepted_at != guard.get("backup_created_at")
    ):
        raise InitializationError("restore_verification_stale")
