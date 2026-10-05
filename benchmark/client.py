"""Public-API access to a reference deployment for the benchmark (M14 D1).

Everything goes through the TLS endpoint with ordinary bearer tokens from the
reference identity provider. No backend, journal or authorization-store access.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from tests.integration.m13 import reference as ref

C1 = "urn:c1:ns:core#"
PROFILES = ("directory", "topics", "batteries")


class Bench:
    """The tested principal is alice; erin authors, carol reviews and reads everything."""

    def __init__(self, case: Any) -> None:
        self.case = case
        self.scopes: dict[str, str] = {}
        self.principals: dict[str, str] = {}

    async def request(
        self, method: str, path: str, *, actor: str = "alice", **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(3):
            try:
                response: httpx.Response = await self.case.request(
                    method, path, actor=actor, **kwargs
                )
                return response
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
        raise AssertionError("unreachable")

    async def json(
        self, method: str, path: str, *, actor: str = "alice", **kwargs: Any
    ) -> dict[str, Any]:
        response = await self.request(method, path, actor=actor, **kwargs)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"{method} {path} as {actor}: {response.status_code} {response.text[:500]}"
            )
        return dict(response.json())

    async def head(self) -> str:
        return str((await self.json("GET", "/v1/instance", actor="carol"))["knowledge_revision"])

    async def apply(
        self, operations: list[dict[str, Any]], *, author: str = "erin", reviewer: str = "carol"
    ) -> dict[str, Any]:
        started = time.perf_counter()
        proposal = await self.json(
            "POST",
            "/v1/changesets",
            actor=author,
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={
                "base_revision": await self.head(),
                "operations": operations,
                "rationale": "M14 benchmark corpus through ordinary C1 APIs",
            },
        )
        path = "/v1/changesets/" + quote(str(proposal["id"]), safe="")
        state = (await self.json("POST", path + "/submit", actor=author))["state"]
        if state == "submitted":
            state = (await self.json("POST", path + "/validate", actor=author))["state"]
        if state != "validated":
            report = await self.json("GET", path + "/validation", actor=author)
            codes = [
                (d.get("code"), d.get("path"), d.get("message"))
                for d in report.get("diagnostics", [])
            ][:10]
            raise RuntimeError(f"benchmark ChangeSet not validated ({state}): {codes}")
        validated = time.perf_counter()
        await self.json("POST", path + "/approve", actor=reviewer)
        approved = time.perf_counter()
        key = uuid.uuid4().hex
        response = await self.request(
            "POST", path + "/apply", actor=reviewer, headers={"Idempotency-Key": key}
        )
        gateway_timeout = response.status_code in (502, 504)
        if gateway_timeout:
            # The proxy gave up while C1 kept applying. Reconcile by reading the
            # ChangeSet; never issue a second apply while the first may run.
            state = "applying"
            deadline = time.monotonic() + 3600
            while state not in {"applied", "failed", "stale", "rejected"}:
                if time.monotonic() > deadline:
                    raise RuntimeError("benchmark ChangeSet apply did not settle")
                await asyncio.sleep(15)
                # While the apply holds its pending operation, the ChangeSet is
                # unavailable (404/503); keep reading until it settles.
                current = await self.request("GET", path, actor=reviewer)
                if current.status_code == 200:
                    state = current.json().get("state", "")
        elif response.status_code != 200:
            raise RuntimeError(f"apply: {response.status_code} {response.text[:300]}")
        else:
            state = response.json().get("state", "")
        if state != "applied":
            raise RuntimeError(f"benchmark ChangeSet not applied: {state}")
        return {
            "seconds": round(time.perf_counter() - started, 3),
            "validate_seconds": round(validated - started, 3),
            "apply_seconds": round(time.perf_counter() - approved, 3),
            "operations": len(operations),
            "gateway_timeout": gateway_timeout,
        }

    async def principal(self, name: str) -> str:
        if name not in self.principals:
            self.principals[name] = (await self.case.principal(name)).id
        return self.principals[name]

    async def grant(self, scope: str, member: str, role: str) -> None:
        await self.case.grant(self.scopes[scope], member, role)

    async def revoke(self, scope: str, member: str, role: str) -> None:
        path = (
            f"/v1/access-scopes/{quote(self.scopes[scope], safe='')}/members/"
            f"{quote(await self.principal(member), safe='')}"
        )
        response = await self.request("DELETE", path, actor="erin", params={"role": role})
        if response.status_code not in (200, 204):
            raise RuntimeError(
                f"revoke {member} {role} on {scope}: {response.status_code} {response.text[:300]}"
            )

    async def setup(self, scopes: tuple[str, ...], visible: tuple[str, ...]) -> dict[str, Any]:
        """Instance roles, profiles and scopes on a freshly bootstrapped deployment."""
        await ref.instance_roles(self.case)
        for member in ("erin", "carol"):
            await self.json(
                "POST",
                "/v1/instance/grants",
                actor="c1admin",
                json={"member": await self.principal(member), "role": "schema_admin"},
            )
        installs = {}
        for name in PROFILES:
            installs[name] = await self.apply([{"kind": "install_profile", "profile": name}])
        for label in scopes:
            self.scopes[label] = await self.case.scope(label)
            for role in ("reviewer", "reader"):
                await self.grant(label, "carol", role)
        for label in visible:
            await self.grant(label, "alice", "reader")
        return {"profiles": installs, "scopes": dict(self.scopes)}


def podman(*argv: str) -> str:
    return subprocess.run(["podman", *argv], capture_output=True, text=True).stdout


def storage_bytes() -> int | None:
    """Size of the TerminusDB storage (knowledge and workflow databases).

    Measured inside the container, so it works for rootful and rootless Podman
    whatever the volume is named.
    """
    out = podman(
        "exec", ref.container("terminusdb"), "du", "-sb", "/app/terminusdb/storage"
    ).split()
    return int(out[0]) if out and out[0].isdigit() else None


def memory_peak() -> int | None:
    out = podman("exec", ref.container("c1"), "cat", "/sys/fs/cgroup/memory.peak").strip()
    return int(out) if out.isdigit() else None


def fga_requests_since(since: str) -> int:
    logs = subprocess.run(
        ["podman", "logs", "--since", since, ref.container("openfga")],
        capture_output=True,
        text=True,
    )
    return (logs.stdout + logs.stderr).count("grpc_req_complete")
