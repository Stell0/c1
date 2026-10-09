"""Commands that run inside the deployment's `tools` container (M13 D5–D8).

They read the same trusted configuration as the C1 service. Output is JSON
on stdout; nothing printed contains a secret value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from importlib import resources
from typing import Any

import httpx

from c1.authorization.fga import FGA, model_definition, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.principal import Principal
from c1.changes.profiles import detect_installed_registry
from c1.config import SECRET_NAMES, Settings, secret_value
from c1.runtime import Runtime, restore_guarded, storage_config
from c1.storage.terminus import Terminus


class AdminError(Exception):
    """A refused administrative step; the message is safe to print."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(name: str) -> str:
    secret = name in SECRET_NAMES or name.endswith("PASSWORD")
    value = secret_value(name) if secret else os.environ.get(name)
    if not value:
        raise AdminError(f"missing configuration {name}")
    return value


# --- Bootstrap ---------------------------------------------------------------


async def _keycloak_token(client: httpx.AsyncClient, base: str) -> str:
    response = await client.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": _required("C1_KEYCLOAK_ADMIN_USER"),
            "password": _required("C1_KEYCLOAK_ADMIN_PASSWORD"),
        },
    )
    if response.status_code != 200:
        raise AdminError("Keycloak bootstrap administrator login failed")
    return str(response.json()["access_token"])


async def bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    """Create the realm, first administrator, authorization store and databases once."""
    base = _required("C1_KEYCLOAK_ADMIN_URL").rstrip("/")
    explorer_secret = secret_value("C1_EXPLORER_CLIENT_SECRET")
    admin_password = secret_value("C1_FIRST_ADMIN_PASSWORD")
    if not explorer_secret or not admin_password:
        raise AdminError("missing Explorer client or first-administrator password file")
    issuer_alias = _required("C1_ISSUER_ALIAS")
    instance_id = _required("C1_INSTANCE_ID")
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        token = await _keycloak_token(client, base)
        headers = {"Authorization": "Bearer " + token}
        existing = await client.get(f"{base}/admin/realms/c1", headers=headers)
        if existing.status_code != 404:
            raise AdminError("realm c1 already exists; bootstrap runs only once")
        template = resources.files("c1.admin").joinpath("realm-c1.json").read_text()
        realm = json.loads(template.replace("@EXPLORER_CLIENT_SECRET@", explorer_secret))
        created = await client.post(f"{base}/admin/realms", headers=headers, json=realm)
        if created.status_code != 201:
            raise AdminError(f"realm import failed ({created.status_code})")
        user = {
            "username": args.admin_user,
            "enabled": True,
            # Keycloak's user profile requires these before the account can sign in.
            "email": args.admin_email or f"{args.admin_user}@example.invalid",
            "firstName": "C1",
            "lastName": "Administrator",
            "emailVerified": True,
            "requiredActions": [] if args.no_temporary_password else ["UPDATE_PASSWORD"],
        }
        made = await client.post(f"{base}/admin/realms/c1/users", headers=headers, json=user)
        if made.status_code != 201:
            raise AdminError(f"first administrator creation failed ({made.status_code})")
        found = await client.get(
            f"{base}/admin/realms/c1/users",
            headers=headers,
            params={"username": args.admin_user, "exact": "true"},
        )
        subject = str(found.json()[0]["id"])
        reset = await client.put(
            f"{base}/admin/realms/c1/users/{subject}/reset-password",
            headers=headers,
            json={
                "type": "password",
                "value": admin_password,
                "temporary": not args.no_temporary_password,
            },
        )
        if reset.status_code != 204:
            raise AdminError("first administrator password could not be set")
    from dataclasses import replace

    from c1.admin.initialization import initialize, load, save

    settings = Settings.from_env(for_initialization=True)
    initialized = await initialize(settings, "bundled-keycloak:" + instance_id)
    settings = replace(
        settings, fga_store=initialized["fga_store"], fga_model=initialized["fga_model"]
    )
    principal = Principal(issuer_alias=issuer_alias, subject=subject, kind="human")
    # Preserve the supported reference bootstrap: the operator explicitly
    # requested and provisioned this account. External initialization never
    # calls this provider-specific provisioning wrapper or grants a principal.
    async with FGA(
        settings.fga_url, settings.fga_token, settings.fga_store, settings.fga_model
    ) as fga:
        instance = "instance:" + instance_id
        for relation in ("access_admin", "schema_admin"):
            await fga.ensure_tuple(principal.id, relation, instance, grant=True)
    async with Journal(storage_config(settings, workflow=True)) as journal:
        await journal.save_many(
            [
                (
                    "Restore",
                    "initial-enrollment",
                    {
                        "type": "enrollment",
                        "principal": principal.id,
                        "operator": "reference-bootstrap",
                        "recorded_at": _now(),
                    },
                )
            ]
        )
    assert settings.initialization_file is not None
    state = load(settings.initialization_file)
    state.update(state="complete", administrator=principal.id, enrolled_at=_now())
    save(settings.initialization_file, state)
    return {
        "fga_store": settings.fga_store,
        "fga_model": settings.fga_model,
        "first_admin_principal": principal.id,
        "model_sha256": _model_digest(),
        "bootstrapped_at": _now(),
    }


def _model_digest() -> str:

    text = json.dumps(model_definition(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


# --- State and consistency -------------------------------------------------


async def _all_tuples(fga: FGA) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    token = ""
    for _ in range(100_000):
        body: dict[str, Any] = {"page_size": 100, "consistency": "HIGHER_CONSISTENCY"}
        if token:
            body["continuation_token"] = token
        payload = await fga._request("POST", fga._path + "/read", json=body)
        for item in payload.get("tuples", []):
            key = item["key"]
            result.append((str(key["user"]), str(key["relation"]), str(key["object"])))
        token = payload.get("continuation_token", "")
        if not token:
            return result
    raise AdminError("authorization tuple read did not finish")


async def _consistency(runtime: Runtime) -> dict[str, Any]:
    """Compare every journal binding with the live OpenFGA `bound_to` tuples."""
    view = await runtime.journal.view()
    live = await runtime.fga.scan_bindings()
    expected: dict[str, list[str]] = {}
    for binding in view.bindings.values():
        if binding.state == "active":
            expected[resource_object(binding.resource_id)] = [scope_object(binding.scope_id)]
    missing = sorted(o for o, users in expected.items() if sorted(live.get(o, [])) != users)
    extra = sorted(o for o in live if o not in expected)
    pending = [
        op.get("id")
        for op in await runtime.journal.list("Operation")
        if op.get("state") == "pending"
    ]
    tuples = await _all_tuples(runtime.fga)
    relations: dict[str, int] = {}
    for _user, relation, obj in tuples:
        if relation == "bound_to":
            continue
        kind = obj.split(":", 1)[0]
        relations[f"{kind}#{relation}"] = relations.get(f"{kind}#{relation}", 0) + 1
    return {
        "security_sha256": __import__("hashlib")
        .sha256(json.dumps(sorted(tuples), separators=(",", ":")).encode())
        .hexdigest(),
        "workflow_head": await runtime.journal.head(),
        "active_bindings": len(expected),
        "binding_mismatches": len(missing),
        "unexpected_bindings": len(extra),
        "pending_operations": len(pending),
        "grant_tuples_by_relation": dict(sorted(relations.items())),
        "consistent": not missing and not extra and not pending,
    }


async def _runtime(*, recover: bool) -> Runtime:
    runtime = Runtime(Settings.from_env())
    try:
        if runtime.settings.initialization_file is not None:
            from c1.admin.initialization import checked

            binding = await runtime.journal.get("Restore", "application-identity")
            if not (
                runtime.settings.identity_mode == "reference"
                and binding is None
                and not runtime.settings.initialization_file.exists()
            ):
                checked(runtime.settings)
        if recover:
            await runtime.start()
        return runtime
    except BaseException:
        await runtime.close()
        raise


async def optimize(_args: argparse.Namespace) -> dict[str, Any]:
    """Optimize the knowledge, workflow and `_system` databases (M14a E1, M14b D5)."""
    import time

    settings = Settings.from_env()
    result: dict[str, Any] = {}
    for name, workflow in (("knowledge", False), ("workflow", True)):
        async with Terminus(storage_config(settings, workflow=workflow)) as storage:
            started = time.perf_counter()
            before = await storage.head()
            await storage.optimize()
            result[name] = {
                "seconds": round(time.perf_counter() - started, 2),
                "head_unchanged": await storage.head() == before,
            }
            if workflow:
                started = time.perf_counter()
                await storage.optimize_system()
                result["system"] = {"seconds": round(time.perf_counter() - started, 2)}
    return result


async def state(_args: argparse.Namespace) -> dict[str, Any]:
    return await inspect_state(Settings.from_env())


async def inspect_state(settings: Settings) -> dict[str, Any]:
    async with Terminus(storage_config(settings)) as knowledge:
        knowledge_head = await knowledge.head()
        registry = await detect_installed_registry(knowledge)
    async with Journal(storage_config(settings, workflow=True)) as journal:
        workflow_head = await journal.head()
        operations = await journal.list("Operation")
        restores = await journal.list("Restore")
    return {
        "knowledge_database": settings.knowledge_database,
        "workflow_database": settings.workflow_database,
        "knowledge_head": knowledge_head,
        "workflow_head": workflow_head,
        "pending_operations": sum(1 for op in operations if op.get("state") == "pending"),
        "profiles": {name: p.version for name, p in sorted(registry.profiles.items())},
        "fga_store": settings.fga_store,
        "fga_model": settings.fga_model,
        "restore_guarded": restore_guarded(restores),
        "restore_records": sorted(
            (
                {
                    "type": str(r.get("type")),
                    "recorded_at": str(r.get("recorded_at")),
                    "released": r.get("released"),
                }
                for r in restores
            ),
            key=lambda r: r["recorded_at"],
        ),
    }


async def consistency(_args: argparse.Namespace) -> dict[str, Any]:
    runtime = await _runtime(recover=False)
    try:
        return await _consistency(runtime)
    finally:
        await runtime.close()


async def _save_restore(payload: dict[str, Any]) -> str:
    settings = Settings.from_env()
    async with Journal(storage_config(settings, workflow=True)) as journal:
        key = str(payload.get("id") or uuid.uuid4())
        payload["id"] = key
        await journal.save_many([("Restore", key, payload)])
        return key


async def knowledge_clone(args: argparse.Namespace) -> dict[str, Any]:
    """Replace the knowledge database with a clone from a restore source (M13 D7).

    The source is a temporary TerminusDB on the backend network serving the
    backup's storage. Cloning keeps the full history and commit identifiers.
    The workflow journal and OpenFGA are not touched.
    """
    import base64

    settings = Settings.from_env()
    source = args.source_url.rstrip("/")
    if not source.startswith("http://") or "@" in source:
        raise AdminError("invalid restore source URL")
    remote = base64.b64encode(f"admin:{settings.terminus_password}".encode()).decode()
    async with Terminus(storage_config(settings)) as knowledge:
        path = knowledge._database_path
        await knowledge._request("DELETE", f"/api/db/{path}")
        await knowledge._request(
            "POST",
            f"/api/clone/{path}",
            headers={"Authorization-Remote": "Basic " + remote},
            json={
                "remote_url": f"{source}/{settings.organization}/{settings.knowledge_database}",
                "label": settings.knowledge_database,
                "comment": "C1 knowledge-only restore",
            },
        )
        return {"knowledge_head": await knowledge.head()}


async def record_restore(args: argparse.Namespace) -> dict[str, Any]:
    key = await _save_restore(
        {
            "type": "knowledge",
            "manifest_sha256": args.manifest_sha256,
            "previous_head": args.previous_head,
            "restored_head": args.restored_head,
            "operator": args.operator,
            "recorded_at": _now(),
        }
    )
    return {"restore_record": key}


async def guard_set(args: argparse.Namespace) -> dict[str, Any]:
    key = await _save_restore(
        {
            "type": "guard",
            "manifest_sha256": args.manifest_sha256,
            "operator": args.operator,
            "released": False,
            "recorded_at": _now(),
        }
    )
    return {"guard": key}


async def _guard(journal: Journal) -> dict[str, Any]:
    guards = [
        r
        for r in await journal.list("Restore")
        if r.get("type") == "guard" and r.get("released") is not True
    ]
    if len(guards) != 1:
        raise AdminError("expected exactly one unreleased restore guard")
    return guards[0]


async def dr_verify(_args: argparse.Namespace) -> dict[str, Any]:
    """Reconcile pending operations, then compare bindings; record the outcome."""
    runtime = await _runtime(recover=True)
    try:
        if runtime.settings.identity_mode == "external":
            from pathlib import Path

            from c1.admin import recovery
            from c1.admin.initialization import InitializationError

            evidence = getattr(_args, "namespace_evidence", None)
            token = getattr(_args, "continuity_token_file", None)
            if not evidence or not token:
                raise InitializationError("namespace_continuity_required")
            return await recovery.verify(runtime, Path(evidence), Path(token))
        result = await _consistency(runtime)
        guard = await _guard(runtime.journal)
        if str(guard.get("id", "")).startswith("external-dr-") and (
            runtime.settings.identity_mode != "external"
        ):
            raise AdminError("external recovery requires external identity configuration")
        guard["verify"] = {**result, "verified_at": _now()}
        await runtime.journal.save_many([("Restore", guard["id"], guard)])
        return result
    finally:
        await runtime.close()


async def dr_release(args: argparse.Namespace) -> dict[str, Any]:
    """Release the guard only after a passing verify and a fresh passing comparison."""
    accepted = datetime.fromisoformat(args.accept_security_as_of)
    if accepted.tzinfo is None:
        raise AdminError("--accept-security-as-of needs a time zone")
    runtime = await _runtime(recover=False)
    try:
        if runtime.settings.identity_mode == "external":
            from pathlib import Path

            from c1.admin import recovery
            from c1.admin.initialization import InitializationError

            evidence = getattr(args, "namespace_evidence", None)
            token = getattr(args, "continuity_token_file", None)
            if not evidence or not token:
                raise InitializationError("namespace_continuity_required")
            await recovery.release_check(
                runtime, Path(evidence), Path(token), args.accept_security_as_of
            )
        guard = await _guard(runtime.journal)
        if not (guard.get("verify") or {}).get("consistent"):
            raise AdminError("dr verify has not passed for this restore")
        if str(guard.get("id", "")).startswith("external-dr-") and (
            runtime.settings.identity_mode != "external"
        ):
            raise AdminError("external recovery requires external identity configuration")
        fresh = await _consistency(runtime)
        if not fresh["consistent"]:
            raise AdminError("security state is no longer consistent; run dr verify again")
        if runtime.settings.identity_mode == "external" and (
            fresh["security_sha256"] != guard["verify"].get("security_sha256")
            or not await runtime.tokens.ready()
        ):
            raise AdminError("external recovery verification is no longer current")
        guard.update(
            {
                "released": True,
                "released_at": _now(),
                "accepted_security_as_of": accepted.isoformat(),
                "reason": args.reason,
                "release_operator": args.operator,
            }
        )
        await runtime.journal.save_many([("Restore", guard["id"], guard)])
        return {"released": guard["id"], "accepted_security_as_of": accepted.isoformat()}
    finally:
        await runtime.close()


def build_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="internal_command", required=True)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--admin-user", default="c1admin")
    boot.add_argument("--no-temporary-password", action="store_true")
    boot.add_argument("--admin-email")
    sub.add_parser("state")
    sub.add_parser("consistency")
    sub.add_parser("optimize")
    clone = sub.add_parser("knowledge-clone")
    clone.add_argument("--source-url", required=True)
    rec = sub.add_parser("record-restore")
    for name in ("--manifest-sha256", "--previous-head", "--restored-head", "--operator"):
        rec.add_argument(name, required=True)
    guard = sub.add_parser("guard-set")
    guard.add_argument("--manifest-sha256", required=True)
    guard.add_argument("--operator", required=True)
    sub.add_parser("dr-verify")
    release = sub.add_parser("dr-release")
    release.add_argument("--accept-security-as-of", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--operator", required=True)


COMMANDS = {
    "bootstrap": bootstrap,
    "state": state,
    "consistency": consistency,
    "optimize": optimize,
    "knowledge-clone": knowledge_clone,
    "record-restore": record_restore,
    "guard-set": guard_set,
    "dr-verify": dr_verify,
    "dr-release": dr_release,
}


def run(args: argparse.Namespace) -> int:
    import asyncio

    try:
        result = asyncio.run(COMMANDS[args.internal_command](args))
    except AdminError as error:
        print(json.dumps({"error": str(error)}), file=sys.stdout)
        return 2
    print(json.dumps(result, sort_keys=True))
    if args.internal_command in {"consistency", "dr-verify"} and not result.get("consistent"):
        return 3
    return 0
