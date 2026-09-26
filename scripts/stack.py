"""Manage only the c1-dev proof stack; never production infrastructure."""

from __future__ import annotations

import argparse
import os
import secrets
import shlex
import subprocess
import time

import httpx

from probes.config import ENV_FILE, ROOT, Settings, environment, runtime

SECRET_KEYS = (
    "C1_TERMINUS_PASSWORD",
    "C1_POSTGRES_PASSWORD",
    "C1_FGA_DB_PASSWORD",
    "C1_FGA_TOKEN",
    "C1_KEYCLOAK_DB_PASSWORD",
    "C1_KEYCLOAK_ADMIN_PASSWORD",
)


def generate_environment() -> None:
    if ENV_FILE.exists():
        values = environment()
        if any(not values.get(key) for key in SECRET_KEYS):
            raise RuntimeError("Existing deployment/.env is incomplete; refusing to overwrite it")
        return
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("# Private random development credentials; never commit this file.\n")
        for key in SECRET_KEYS:
            stream.write(f"{key}={secrets.token_hex(24)}\n")


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
    elif args.action == "down":
        compose(["down"])
    elif args.action == "reset":
        # Exact compose file/project bounds removal to the two declared dev volumes.
        compose(["down", "--volumes"])
    else:
        wait_ready()


if __name__ == "__main__":
    main()
