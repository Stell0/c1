"""Manage only the c1-dev proof stack; never production infrastructure."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import time

import httpx

from probes.config import ENV_FILE, ROOT, Settings, environment, runtime
from scripts.bootstrap_security import bootstrap, ensure_environment


def generate_environment() -> None:
    ensure_environment()


def redact(text: str) -> str:
    for value in environment().values():
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def compose(arguments: list[str]) -> None:
    command = shlex.split(os.environ.get("COMPOSE", "podman compose"))
    command += [
        "-p",
        "c1-dev",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(ROOT / "deployment/compose.yaml"),
        *arguments,
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print(redact(result.stdout + result.stderr)[-12000:])
        raise RuntimeError(f"c1-dev compose {arguments[0]} failed (exit {result.returncode})")
    print(f"c1-dev compose {arguments[0]} completed")


def container_id(service: str) -> str:
    if service not in {"terminusdb", "postgres", "openfga", "keycloak"}:
        raise ValueError("Not an M01 service")
    result = subprocess.check_output(
        [
            runtime(),
            "ps",
            "-a",
            "--filter",
            "label=com.docker.compose.project=c1-dev",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ],
        text=True,
    ).splitlines()
    if len(result) != 1:
        raise RuntimeError(f"Expected exactly one owned c1-dev {service} container")
    return result[0]


def wait_ready(timeout: float = 180) -> None:
    settings = Settings.load()
    deadline = time.monotonic() + timeout
    endpoints: dict[str, tuple[str, dict[str, str]]] = {
        "terminusdb": (settings.terminus_url + "/api/info", {}),
        "openfga": (settings.fga_url + "/healthz", {}),
        "keycloak": (settings.keycloak_url + "/realms/c1-dev/.well-known/openid-configuration", {}),
    }
    pending = set(endpoints)
    with httpx.Client(timeout=3, trust_env=False) as client:
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                try:
                    url, _ = endpoints[name]
                    auth = ("admin", settings.terminus_password) if name == "terminusdb" else None
                    response = client.get(url, auth=auth)
                    if response.status_code == 200:
                        pending.remove(name)
                        print(f"{name}: ready")
                except httpx.HTTPError:
                    pass
            if pending:
                time.sleep(1)
    if pending:
        raise RuntimeError("Readiness deadline exceeded: " + ", ".join(sorted(pending)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "reset", "ready"])
    args = parser.parse_args()
    if args.action == "up":
        generate_environment()
        compose(["up", "-d"])
        wait_ready()
        bootstrap()
    elif args.action == "down":
        compose(["down"])
    elif args.action == "reset":
        # Exact compose file/project bounds removal to the two declared dev volumes.
        compose(["down", "--volumes"])
    else:
        wait_ready()


if __name__ == "__main__":
    main()
