"""Application initialization and operator approval, independent of deployment engines.

Intent is fsynced before backend mutations. Database ownership is pinned in
backend metadata and an unpredictable store name is persisted before creation.
The protected local state is application-owned and must accompany a full backup.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from c1.authorization.fga import FGA, model_definition
from c1.authorization.journal import _ENTRY_CLASS, _RECORD_CLASS, Journal
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.model.profiles import ProfileRegistry
from c1.runtime import storage_config
from c1.storage.schema import assert_installed_profiles
from c1.storage.terminus import Terminus

VERSION = 1


class InitializationError(ValueError):
    """Stable safe error category; never backend messages or secret values."""


def identity(settings: Settings) -> dict[str, Any]:
    return {
        "instance_id": settings.instance_id,
        "instance_base": settings.instance_base,
        "issuer": settings.issuer,
        "issuer_alias": settings.issuer_alias,
        "audience": settings.audience,
        "identity_mode": settings.identity_mode,
        "oidc_config_version": settings.oidc_config_version,
        "explorer_client_id": settings.explorer_client_id,
        "token_profile": settings.oidc_token_profile,
        "kind_claim": settings.principal_kind_claim,
        "kind_mapping": dict(settings.principal_kind_mapping),
        "organization": settings.organization,
        "knowledge_database": settings.knowledge_database,
        "workflow_database": settings.workflow_database,
    }


def load(path: Path) -> dict[str, Any]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 65536:
                raise InitializationError("unsafe_initialization_file")
            value = json.load(stream)
    except (OSError, ValueError) as exc:
        if isinstance(exc, InitializationError):
            raise
        raise InitializationError("initialization_state_unavailable") from None
    if not isinstance(value, dict) or value.get("contract_version") != VERSION:
        raise InitializationError("incompatible_initialization_state")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    # The supervisor provisions a private persistent directory; never chmod
    # someone else's parent or follow a symlink during an atomic replacement.
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise InitializationError("unsafe_initialization_directory")
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def lock(path: Path) -> Iterator[None]:
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise InitializationError("initialization_busy") from None
    finally:
        os.close(fd)


def checked(settings: Settings) -> dict[str, Any] | None:
    if settings.initialization_file is None:
        return None
    state = load(settings.initialization_file)
    if state.get("identity") != identity(settings):
        raise InitializationError("identity_configuration_changed")
    if state.get("fga_store") != settings.fga_store or state.get("fga_model") != settings.fga_model:
        raise InitializationError("authorization_configuration_changed")
    return state


def guarded(settings: Settings) -> bool:
    try:
        state = checked(settings)
        return state is not None and state.get("state") != "complete"
    except InitializationError:
        return True


def approve(settings: Settings, issuer: str, subject: str, operator: str, lifetime: int) -> None:
    if settings.initialization_file is None:
        raise InitializationError("initialization_file_required")
    if issuer != settings.issuer or not operator or not 60 <= lifetime <= 86400:
        raise InitializationError("invalid_enrollment_approval")
    Principal(settings.issuer_alias, subject, "human")
    with lock(settings.initialization_file):
        state = checked(settings)
        if state is None or state.get("state") not in {
            "awaiting_enrollment",
            "approved",
            "enrolling",
        }:
            raise InitializationError("enrollment_not_available")
        started = state["state"] == "enrolling"
        if started and any(
            state.get("approval", {}).get(k) != v
            for k, v in {"issuer": issuer, "subject": subject}.items()
        ):
            raise InitializationError("enrollment_not_available")
        # Once a grant might have been written, replacement could strand an
        # unintended administrator. Recovery must finish the exact same intent.
        state.update(
            state="enrolling" if started else "approved",
            approval={
                "issuer": issuer,
                "subject": subject,
                "operator": operator,
                "expires_at": time.time() + lifetime,
            },
        )
        save(settings.initialization_file, state)


def cancel(settings: Settings) -> None:
    if settings.initialization_file is None:
        raise InitializationError("initialization_file_required")
    with lock(settings.initialization_file):
        state = checked(settings)
        if state is None or state.get("state") not in {"awaiting_enrollment", "approved"}:
            raise InitializationError("enrollment_not_available")
        state.pop("approval", None)
        state["state"] = "awaiting_enrollment"
        save(settings.initialization_file, state)


async def _database(storage: Terminus, owner: str, *, allow_create: bool = True) -> None:
    response = await storage._request("GET", "/api/db", params={"verbose": "true"})
    databases = response.json()
    if not isinstance(databases, list):
        raise InitializationError("invalid_database_inventory")
    matches = [d for d in databases if d.get("path") == storage._database_path]
    if not matches:
        if not allow_create:
            raise InitializationError("owned_database_missing")
        await storage._request(
            "POST",
            "/api/db/" + storage._database_path,
            json={"label": storage.config.database, "comment": owner},
        )
    elif len(matches) != 1 or matches[0].get("comment") != owner:
        raise InitializationError("ambiguous_database_ownership")


async def _store(fga: FGA, state: dict[str, Any], path: Path) -> None:
    stores: list[dict[str, Any]] = []
    token = ""
    for _ in range(100):
        page = await fga._request(
            "GET", "/stores", params={"page_size": 100, "continuation_token": token}
        )
        stores.extend(page.get("stores", []))
        token = page.get("continuation_token", "")
        if not token:
            break
    else:
        raise InitializationError("store_inventory_limit")
    matches = [store for store in stores if store.get("name") == state["owner"]]
    if len(matches) > 1:
        raise InitializationError("ambiguous_store_ownership")
    if not matches:
        if state.get("fga_store"):
            raise InitializationError("owned_authorization_store_missing")
        result = await fga._request("POST", "/stores", json={"name": state["owner"]})
        fga.store_id = str(result["id"])
    else:
        fga.store_id = str(matches[0]["id"])
    if state.get("fga_store") not in (None, fga.store_id):
        raise InitializationError("authorization_configuration_changed")
    state["fga_store"] = fga.store_id
    save(path, state)
    models = await fga._request("GET", fga._path + "/authorization-models")
    # Compare semantic JSON keys (OpenFGA emits camelCase).
    from c1.authorization.fga import _snake_keys

    expected = _model_shape(_snake_keys(model_definition()))
    matching = [
        m
        for m in models.get("authorization_models", [])
        if _model_shape(_snake_keys({k: v for k, v in m.items() if k != "id"})) == expected
    ]
    if len(matching) > 1:
        raise InitializationError("ambiguous_model_ownership")
    if matching:
        fga.model_id = str(matching[0]["id"])
    elif models.get("authorization_models"):
        raise InitializationError("incompatible_authorization_model")
    else:
        if state.get("fga_model"):
            raise InitializationError("owned_authorization_model_missing")
        made = await fga._request(
            "POST", fga._path + "/authorization-models", json=model_definition()
        )
        fga.model_id = str(made["authorization_model_id"])
    if state.get("fga_model") not in (None, fga.model_id):
        raise InitializationError("authorization_configuration_changed")
    state["fga_model"] = fga.model_id
    save(path, state)


def _model_shape(value: Any) -> Any:
    """Remove only OpenFGA's empty protobuf defaults, preserving this:{}.

    Nonempty conditions, relation rewrites and user-type restrictions are
    retained and compared, so this is not just a read-shape readiness check.
    """
    if isinstance(value, dict):
        defaults = {
            "metadata",
            "conditions",
            "relations",
            "condition",
            "module",
            "source_info",
            "object",
        }
        return {
            k: _model_shape(v)
            for k, v in value.items()
            if not (k in defaults and v in (None, "", {}))
        }
    if isinstance(value, list):
        return [_model_shape(v) for v in value]
    return value


async def initialize(settings: Settings, namespace_id: str) -> dict[str, Any]:
    path = settings.initialization_file
    if path is None or not namespace_id or len(namespace_id) > 255:
        raise InitializationError("initialization_metadata_required")
    if settings.identity_mode == "external" and settings.explorer_client_id is None:
        raise InitializationError("explorer_registration_required")
    with lock(path):
        backends = {"terminus_url": settings.terminus_url, "fga_url": settings.fga_url}
        if path.exists():
            state = load(path)
            if (
                state.get("identity") != identity(settings)
                or state.get("namespace_id") != namespace_id
                or state.get("backend_origins") != backends
            ):
                raise InitializationError("identity_configuration_changed")
        else:
            # Never adopt an existing backend using only a local receipt.
            state = {
                "contract_version": VERSION,
                "identity": identity(settings),
                "namespace_id": namespace_id,
                "owner": "c1-" + uuid.uuid4().hex,
                "state": "partial",
                "steps": [],
                "backend_origins": backends,
                "started_at": datetime.now(UTC).isoformat(),
            }
            save(path, state)
        async with FGA(
            settings.fga_url, settings.fga_token, timeout=settings.backend_timeout_s
        ) as fga:
            await _store(fga, state, path)
            current = replace(settings, fga_store=fga.store_id, fga_model=fga.model_id)
            async with Journal(storage_config(current, workflow=True)) as journal:
                await _database(
                    journal._storage, state["owner"], allow_create="workflow" not in state["steps"]
                )
                schema = await journal._storage.schema_documents()
                if not any(d.get("@id") == "WorkflowEntry" for d in schema):
                    await journal._storage._insert(
                        [_ENTRY_CLASS, _RECORD_CLASS],
                        expected_head=await journal.head(),
                        message="Install C1 workflow journal schema",
                        graph_type="schema",
                    )
                if not await journal.ready():
                    raise InitializationError("incompatible_workflow_schema")
                if "workflow" not in state["steps"]:
                    state["steps"].append("workflow")
                    save(path, state)
            async with Terminus(storage_config(current)) as knowledge:
                await _database(
                    knowledge, state["owner"], allow_create="core_profile" not in state["steps"]
                )
                registry = ProfileRegistry()
                schema = await knowledge.schema_documents()
                if len(schema) == 1:
                    await knowledge.install_profile(registry)
                else:
                    from c1.storage.mapping import record_to_document
                    from c1.storage.schema import _assert_authority, _profile_marker

                    _assert_authority(schema, registry)
                    marker = record_to_document(
                        _profile_marker(registry, "core"), registry, current.instance_base
                    )
                    if await knowledge.get(marker["@id"]) is None:
                        if await knowledge.documents():
                            raise InitializationError("ambiguous_core_profile_state")
                        await knowledge._insert(
                            [marker],
                            expected_head=await knowledge.head(),
                            message="Recover C1 core profile version",
                        )
                await assert_installed_profiles(knowledge, registry)
                if "core_profile" not in state["steps"]:
                    state["steps"].append("core_profile")
                    save(path, state)
            async with Journal(storage_config(current, workflow=True)) as journal:
                binding = {
                    "type": "initialization",
                    "identity": state["identity"],
                    "fga_store": state["fga_store"],
                    "fga_model": state["fga_model"],
                    "namespace_id": namespace_id,
                    "owner": state["owner"],
                    "recorded_at": state["started_at"],
                }
                existing = await journal.get("Restore", "application-identity")
                if existing is not None and existing != binding:
                    raise InitializationError("identity_configuration_changed")
                if existing is None:
                    await journal.save_many([("Restore", "application-identity", binding)])
            if state["state"] == "partial":
                state["state"] = "awaiting_enrollment"
            state["steps"] = ["store", "model", "workflow", "core_profile"]
            state["schema_versions"] = {"core": registry.profiles["core"].version, "workflow": "1"}
            state["authorization_model_version"] = model_definition()["schema_version"]
            state["model_sha256"] = hashlib.sha256(
                json.dumps(model_definition(), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            save(path, state)
        return {
            "contract_version": VERSION,
            "state": state["state"],
            "fga_store": state["fga_store"],
            "fga_model": state["fga_model"],
            "initialization_file": str(path),
        }
