"""Run one disposable loopback C1 API process for M03 crash/recovery tests."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from probes.config import ROOT, environment

HOST = "127.0.0.1"
PORT = 18000
PID_FILE = ROOT / "deployment/.state/api.pid"
LOG_FILE = ROOT / "docs/evidence/M03/api.log"
APP_MARKER = "scripts.api:app_factory"


def app_factory() -> object:
    """Uvicorn factory; all backend routing comes from trusted process env."""
    from c1.api.app import create_app
    from c1.config import Settings

    return create_app(Settings.from_env())


def _owned_process(pid: int) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return False
    return b"uvicorn" in command and APP_MARKER.encode() in command


def _pid() -> int | None:
    try:
        payload = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("pid") if isinstance(payload, dict) else None
    return value if type(value) is int and value > 0 else None


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.2):
            return True
    except OSError:
        return False


def _environment(crash_after: str | None) -> dict[str, str]:
    private = environment()
    if not private:
        raise RuntimeError("deployment/.env is missing; start the pinned stack first")
    # A trusted test launcher may select its isolated databases/store without
    # rewriting the private stack file. Process environment takes precedence.
    values = {**private, **os.environ}
    values["C1_ENABLE_PROBE_ROUTES"] = "true"
    if crash_after is not None:
        values["C1_CRASH_AFTER"] = crash_after
    else:
        values.pop("C1_CRASH_AFTER", None)
    return values


def up(crash_after: str | None) -> None:
    """Refuse a second process or an occupied port; retain only the child PID."""
    old = _pid()
    if old is not None and _owned_process(old):
        raise RuntimeError("the owned C1 API process is already running")
    if _port_open():
        raise RuntimeError("API port is occupied; refusing to start a second process")
    if PID_FILE.exists():
        PID_FILE.unlink()
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                APP_MARKER,
                "--factory",
                "--host",
                HOST,
                "--port",
                str(PORT),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=_environment(crash_after),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        descriptor = os.open(PID_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": process.pid}, stream)
            stream.write("\n")
        # Readiness itself waits on bounded backend timeouts. During recovery
        # fault tests, OpenFGA may be intentionally paused and return 503 only
        # after the configured backend client deadline (default 5 s, M09 D13).
        backend = float(_environment(crash_after).get("C1_BACKEND_TIMEOUT_S", "5"))
        deadline = time.monotonic() + max(30.0, 2 * backend + 20)
        with httpx.Client(timeout=max(15.0, backend + 10), trust_env=False) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"C1 API exited during startup ({process.returncode})")
                try:
                    response = client.get(f"http://{HOST}:{PORT}/v1/readyz")
                    if response.status_code in {200, 503}:
                        print(f"C1 API listening on {HOST}:{PORT}; pid {process.pid}")
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
        raise RuntimeError("C1 API health deadline exceeded")
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        PID_FILE.unlink(missing_ok=True)
        raise


def down() -> None:
    pid = _pid()
    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        print("C1 API is not running")
        return
    if not _owned_process(pid):
        PID_FILE.unlink(missing_ok=True)
        print("C1 API is not running")
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _owned_process(pid):
        time.sleep(0.1)
    if _owned_process(pid):
        raise RuntimeError("C1 API did not stop after SIGTERM")
    PID_FILE.unlink(missing_ok=True)
    print("C1 API stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "down"))
    parser.add_argument("--crash-after", choices=("journal", "tuple", "confirm"))
    args = parser.parse_args()
    if args.action == "up":
        up(args.crash_after)
    else:
        if args.crash_after is not None:
            parser.error("--crash-after applies only to up")
        down()


if __name__ == "__main__":
    main()
