"""Versioned public operator CLI for application-owned state only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from c1.admin import contracts, initialization, internal, recovery
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGAError
from c1.authorization.operations import WriterGate
from c1.config import Settings
from c1.storage.terminus import BackendError, StorageError


def build_parser(sub: Any) -> None:
    parser = sub.add_parser("application", help="provider-independent application operations")
    commands = parser.add_subparsers(dest="application_command", required=True)
    commands.add_parser("contract", help="versioned operation schemas and capabilities")
    init = commands.add_parser("initialize")
    init.add_argument("--namespace-id", required=True)
    approve = commands.add_parser("enrollment-approve")
    approve.add_argument("--issuer", required=True)
    approve.add_argument("--subject", required=True)
    approve.add_argument("--operator", required=True)
    approve.add_argument("--expires-in", type=int, default=3600)
    commands.add_parser("enrollment-cancel")
    commands.add_parser("state")
    oidc = commands.add_parser("oidc-check")
    oidc.add_argument("--token-file")
    for name in ("consistency", "optimize", "dr-verify"):
        operation = commands.add_parser(name)
        if name == "dr-verify":
            operation.add_argument("--namespace-evidence")
            operation.add_argument("--continuity-token-file")
    backup = commands.add_parser("backup-manifest")
    backup.add_argument("--directory", required=True)
    backup.add_argument("--operator", required=True)
    restore = commands.add_parser("restore-validate")
    restore.add_argument("--directory", required=True)
    restore.add_argument("--operator", required=True)
    guard = commands.add_parser("guard-set")
    guard.add_argument("--manifest-sha256", required=True)
    guard.add_argument("--operator", required=True)
    release = commands.add_parser("dr-release")
    release.add_argument("--accept-security-as-of", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--operator", required=True)
    release.add_argument("--namespace-evidence")
    release.add_argument("--continuity-token-file")


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    command = args.application_command
    if command == "contract":
        return {
            "contract_version": 1,
            "capabilities": {
                "initialize": True,
                "explicit_enrollment": True,
                "external_oidc": True,
                "production_qualified": False,
                "gate_a_qualified": False,
            },
            "token_profiles": ["c1-v1", "rfc9068-v1", "hydra-jwt-v1"],
            "configuration": "C1_* environment and protected *_FILE secrets",
            "states": [
                "empty",
                "partial",
                "awaiting_enrollment",
                "approved",
                "enrolling",
                "complete",
                "incompatible",
            ],
            "exclusive": [
                "initialize",
                "guard-set",
                "backup-manifest",
                "restore-validate",
                "dr-verify",
                "dr-release",
            ],
            "online": [
                "state",
                "consistency",
                "enrollment-approve",
                "enrollment-cancel",
                "optimize",
                "oidc-check",
            ],
            "operator_timeout_s": {"default": 300, "minimum": 30, "maximum": 3600},
            "credential_requirements": {
                "backends": ["C1_TERMINUS_PASSWORD[_FILE]", "C1_FGA_TOKEN[_FILE]"],
                "browser": ["C1_EXPLORER_CLIENT_SECRET[_FILE]"],
                "identity_administration": [],
                "external_recovery": "protected continuity evidence and normal user access token",
            },
            "exit_codes": {"success": 0, "refused": 2, "inconsistent": 3, "unavailable": 4},
            "schemas": contracts.schemas(),
        }
    if command == "state" and os.environ.get("C1_INITIALIZATION_FILE"):
        path = Path(os.environ["C1_INITIALIZATION_FILE"])
        if not path.is_absolute() or path.is_symlink():
            raise initialization.InitializationError("unsafe_initialization_file")
        if not path.exists():
            return {"state": "empty", "ready": False}
    settings = Settings.from_env(
        for_initialization=command in {"initialize", "state", "oidc-check"}
    )
    if command == "oidc-check":
        from c1.authorization.tokens import AuthenticationError, TokenValidator
        from c1.config import ExplorerSettings
        from c1.explorer.oidc import LoginError, OIDCClient

        explorer = ExplorerSettings.from_env()
        if explorer is None:
            raise initialization.InitializationError("explorer_registration_required")
        client = OIDCClient(
            settings.issuer,
            explorer,
            timeout_s=settings.backend_timeout_s,
            verify=settings.issuer_verify(),
            allowed_endpoints=settings.oidc_endpoint_urls,
            api_audience=settings.audience,
        )
        validator = TokenValidator(settings)
        try:
            endpoints = await client.endpoints()
            if not await validator.ready():
                raise initialization.InitializationError("oidc_signing_keys_unavailable")
            if args.token_file:
                path = Path(args.token_file)
                recovery.digest(path)
                if path.stat().st_size > 16384:
                    raise initialization.InitializationError("invalid_token_file")
                await validator.authenticate(path.read_text().strip())
            return {
                "metadata_compatible": True,
                "access_token_verified": bool(args.token_file),
                "logout_advertised": endpoints.end_session is not None,
                "token_profile": settings.oidc_token_profile,
                "client_registration": "externally_managed",
            }
        except LoginError as exc:
            raise initialization.InitializationError("oidc_" + str(exc)) from None
        except AuthenticationError as exc:
            raise initialization.InitializationError(
                "unsupported_access_token_" + exc.reason
            ) from None
        finally:
            await client.close()
            await validator.close()
    if command == "initialize":
        contracts.InitializeInput(namespace_id=args.namespace_id)
        if settings.identity_mode != "external":
            raise initialization.InitializationError("external_identity_required")
        writer = WriterGate(settings.lock_path)
        try:
            async with writer.hold():
                return await initialization.initialize(settings, args.namespace_id)
        finally:
            writer.close()
    if command == "enrollment-approve":
        contracts.EnrollmentApprovalInput(
            issuer=args.issuer,
            subject=args.subject,
            operator=args.operator,
            expires_in=args.expires_in,
        )
        initialization.approve(settings, args.issuer, args.subject, args.operator, args.expires_in)
        return {"state": "approved"}
    if command == "enrollment-cancel":
        initialization.cancel(settings)
        return {"state": "awaiting_enrollment"}
    if command == "state":
        state = None
        if settings.initialization_file is not None:
            state = initialization.load(settings.initialization_file)
            if state.get("identity") != initialization.identity(settings):
                raise initialization.InitializationError("identity_configuration_changed")
        if state is not None and state["state"] != "complete":
            return {
                "state": state["state"],
                "ready": False,
                "fga_store": state.get("fga_store"),
                "fga_model": state.get("fga_model"),
            }
        if state is not None:
            for name in ("fga_store", "fga_model"):
                if getattr(settings, name) not in {"pending", state[name]}:
                    raise initialization.InitializationError("authorization_configuration_changed")
            settings = replace(settings, fga_store=state["fga_store"], fga_model=state["fga_model"])
        return {
            "state": "complete",
            "readiness": "check_live_readyz",
            **await internal.inspect_state(settings),
        }
    if settings.identity_mode == "external" and command in {
        "backup-manifest",
        "restore-validate",
        "dr-verify",
        "dr-release",
    }:
        runtime = await internal._runtime(recover=command == "dr-verify")
        from c1.changes.profiles import detect_installed_registry

        writer = WriterGate(settings.lock_path)
        try:
            runtime.registry = await detect_installed_registry(runtime.knowledge)

            async def operation() -> dict[str, Any]:
                if command == "backup-manifest":
                    return await recovery.manifest(runtime, Path(args.directory), args.operator)
                if command == "restore-validate":
                    return await recovery.restore_validate(
                        runtime, Path(args.directory), args.operator
                    )
                if not args.namespace_evidence or not args.continuity_token_file:
                    raise initialization.InitializationError("namespace_continuity_required")
                evidence, token = Path(args.namespace_evidence), Path(args.continuity_token_file)
                if command == "dr-verify":
                    return await recovery.verify(runtime, evidence, token)
                await recovery.release_check(runtime, evidence, token, args.accept_security_as_of)
                return await internal.dr_release(args)

            if command == "dr-verify":
                return await operation()
            async with writer.hold():
                return await operation()
        finally:
            writer.close()
            await runtime.close()
    # These already operate on configured application backends; no host engine.
    writer = WriterGate(settings.lock_path)
    try:
        if command in {"guard-set", "dr-release"}:
            async with writer.hold():
                return await internal.COMMANDS[command](args)
        return await internal.COMMANDS[command](args)
    finally:
        writer.close()


def run(args: argparse.Namespace) -> int:
    async def bounded() -> dict[str, Any]:
        limit = int(os.environ.get("C1_OPERATOR_TIMEOUT_S", "300"))
        if not 30 <= limit <= 3600:
            raise initialization.InitializationError("invalid_operator_timeout")
        async with asyncio.timeout(limit):
            return await execute(args)

    try:
        result = asyncio.run(bounded())
    except TimeoutError:
        print(json.dumps({"contract_version": 1, "error": "operator_timeout"}))
        return 4
    except (initialization.InitializationError, internal.AdminError, ValueError) as exc:
        category = (
            str(exc) if isinstance(exc, initialization.InitializationError) else "invalid_input"
        )
        print(json.dumps({"contract_version": 1, "error": category}))
        return (
            4
            if category
            in {
                "identity_service_unavailable",
                "oidc_identity_unavailable",
                "oidc_signing_keys_unavailable",
                "enrollment_consistency_unavailable",
                "enrollment_grants_unavailable",
            }
            else 2
        )
    except (BackendError, StorageError, FGAError, SecurityError, httpx.HTTPError, OSError):
        print(json.dumps({"contract_version": 1, "error": "backend_unavailable"}))
        return 4
    except Exception:
        print(json.dumps({"contract_version": 1, "error": "operator_failure"}))
        return 4
    print(json.dumps({"contract_version": 1, **result}, sort_keys=True))
    return 3 if result.get("consistent") is False else 0
