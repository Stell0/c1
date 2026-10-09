"""Kill a real C1 process immediately after a selected durable boundary.

Original file/backend operations run unchanged against pinned real services;
the hook adds SIGKILL, not a mocked transaction or a fake success response.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any


def install(boundary: str) -> None:
    from pytest import MonkeyPatch

    patch = MonkeyPatch()
    from c1.admin import initialization
    from c1.authorization.fga import FGA
    from c1.authorization.journal import Journal
    from c1.storage.terminus import Terminus

    def kill(name: str) -> None:
        if boundary == name:
            os.kill(os.getpid(), signal.SIGKILL)

    original_save = initialization.save

    def save(path: Path, value: dict[str, Any]) -> None:
        state = value
        original_save(path, state)
        if "state" not in state:
            if state.get("type") == "external-full":
                kill("backup_manifest_response")
            return
        if state["state"] == "partial" and not state.get("fga_store"):
            kill("intent")
        if state["state"] == "partial" and state.get("fga_store"):
            if not state.get("fga_model"):
                kill("store_checkpoint")
            elif "workflow" not in state["steps"]:
                kill("model_checkpoint")
            elif "core_profile" not in state["steps"]:
                kill("workflow_checkpoint")
            else:
                kill("core_checkpoint")
        if state["state"] == "enrolling":
            kill("enrollment_intent")
        if state["state"] == "approved":
            kill("approval_checkpoint")
        if state["state"] == "complete":
            kill("enrollment_complete")
        if state["state"] == "awaiting_enrollment":
            kill("initialization_complete")

    initialization.save = save
    original_fga = FGA._request

    async def fga(self: FGA, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        result = await original_fga(self, method, path, **kwargs)
        if method == "POST":
            if path == "/stores":
                kill("store_response")
            elif path.endswith("/authorization-models"):
                kill("model_response")
            elif path.endswith("/write"):
                for key in kwargs.get("json", {}).get("writes", {}).get("tuple_keys", []):
                    if key.get("relation") == "access_admin":
                        kill("enrollment_access_grant")
                    if key.get("relation") == "schema_admin":
                        kill("enrollment_schema_grant")
        return result

    patch.setattr(FGA, "_request", fga)
    original_storage = Terminus._request

    async def storage(self: Terminus, method: str, path: str, **kwargs: Any) -> Any:
        result = await original_storage(self, method, path, **kwargs)
        workflow = self.config.database == os.environ["C1_WORKFLOW_DATABASE"]
        name = "workflow" if workflow else "knowledge"
        if method == "POST" and path.startswith("/api/db/"):
            kill(name + "_database_response")
        if method == "POST" and path.startswith("/api/document/"):
            if kwargs.get("params", {}).get("graph_type") == "schema":
                kill(name + "_schema_response")
            elif not workflow:
                kill("core_marker_response")
        return result

    patch.setattr(Terminus, "_request", storage)
    original_journal = Journal.save_many

    async def journal(self: Journal, entries: Any, *, expected_head: str | None = None) -> Any:
        result = await original_journal(self, entries, expected_head=expected_head)
        if any(kind == "Restore" and key == "application-identity" for kind, key, _ in entries):
            kill("identity_binding_response")
        if any(kind == "Restore" and key == "initial-enrollment" for kind, key, _ in entries):
            kill("enrollment_audit_response")
        for kind, _, value in entries:
            if kind == "Restore" and value.get("type") == "guard":
                if value.get("released"):
                    kill("recovery_release_response")
                elif value.get("verify"):
                    kill("recovery_verify_response")
                else:
                    kill("restore_guard_response")
        return result

    patch.setattr(Journal, "save_many", journal)
