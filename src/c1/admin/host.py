"""Host-side orchestration of the reference deployment (M13 D5–D8).

Uses the container engine and compose CLI; never prints secret values.
Backup files carry secret-bearing data and are written mode 0600 in a
mode-0700 directory.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from c1.admin.certs import dev_certs

SECRET_FILES = (
    "terminus_password",
    "postgres_password",
    "fga_db_password",
    "fga_token",
    "cursor_secret",
    "keycloak_db_password",
    "keycloak_admin_password",
    "explorer_client_secret",
    "admin_password",
)
BACKENDS = ("postgres", "terminusdb", "openfga-migrate", "openfga", "keycloak")
HEALTHY = ("postgres", "terminusdb", "openfga", "keycloak")
MANIFEST_VERSION = 1


class HostError(Exception):
    """A refused or failed host step; the message is safe to print."""


class Deployment:
    def __init__(self, directory: Path, project: str, env: dict[str, str] | None = None) -> None:
        self.dir = directory.resolve()
        self.project = project
        self.env = {**os.environ, **(env or {})}
        self.engine = self.env.get("C1_ENGINE", "podman")
        self.compose_cmd = shlex.split(self.env.get("C1_COMPOSE", "podman-compose"))

    # Engine helpers ---------------------------------------------------------

    def run(
        self, argv: list[str], *, input: bytes | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            argv, input=input, capture_output=True, env=self.env, cwd=self.dir, check=False
        )
        if check and result.returncode != 0:
            tail = result.stderr.decode(errors="replace")[-600:]
            raise HostError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed: {tail}")
        return result

    def compose(
        self, *args: str, check: bool = True, profile: str | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        selected = ["--profile", profile] if profile else []
        return self.run(
            [
                *self.compose_cmd,
                *selected,
                "-p",
                self.project,
                "-f",
                str(self.dir / "compose.yaml"),
                *args,
            ],
            check=check,
        )

    def container(self, service: str) -> str:
        output = (
            self.run(
                [
                    self.engine,
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={self.project}",
                    "--filter",
                    f"label=com.docker.compose.service={service}",
                    "--format",
                    "{{.Names}}",
                ]
            )
            .stdout.decode()
            .split()
        )
        if len(output) != 1:
            raise HostError(f"expected one {service} container in {self.project}")
        return output[0]

    def wait_healthy(self, services: tuple[str, ...], timeout: float = 900) -> None:
        deadline = time.monotonic() + timeout
        pending = list(services)
        while pending and time.monotonic() < deadline:
            for service in list(pending):
                try:
                    name = self.container(service)
                except HostError:
                    continue
                status = (
                    self.run(
                        [self.engine, "inspect", "--format", "{{.State.Health.Status}}", name],
                        check=False,
                    )
                    .stdout.decode()
                    .strip()
                )
                if status == "healthy":
                    pending.remove(service)
            if pending:
                time.sleep(3)
        if pending:
            raise HostError("services not healthy: " + ", ".join(pending))

    def internal(self, *args: str) -> dict[str, Any]:
        result = self.compose(
            "run",
            "--rm",
            "-T",
            "tools",
            "c1-admin",
            "internal",
            *args,
            check=False,
            profile="tools",
        )
        lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
        if not lines:
            tail = result.stderr.decode(errors="replace")[-800:]
            raise HostError(f"tools command {args[0]} produced no result: {tail}")
        payload: dict[str, Any] = json.loads(lines[-1])
        payload["_exit"] = result.returncode
        if "error" in payload:
            raise HostError(str(payload["error"]))
        return payload


def _write_secret(path: Path, value: str, mode: int = 0o444) -> None:
    # Third-party images read secret files as non-root users inside their own
    # container; the mode-0700 directory keeps the files private on the host.
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(mode)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _operator(args: argparse.Namespace) -> str:
    return str(getattr(args, "operator", None) or getpass.getuser())


def prepare(d: Deployment, prefix: str) -> dict[str, str]:
    """Secrets, test certificates and rendered configuration; existing files are kept."""
    secrets_dir = d.dir / "secrets"
    secrets_dir.mkdir(mode=0o700, exist_ok=True)
    secrets_dir.chmod(0o700)
    for name in SECRET_FILES:
        path = secrets_dir / name
        if not path.exists():
            _write_secret(path, secrets.token_urlsafe(32))
    env_file = secrets_dir / "openfga.env"
    if not env_file.exists():
        fga_db = (secrets_dir / "fga_db_password").read_text().strip()
        fga_token = (secrets_dir / "fga_token").read_text().strip()
        env_file.write_text(
            f"OPENFGA_DATASTORE_PASSWORD={fga_db}\nOPENFGA_AUTHN_PRESHARED_KEYS={fga_token}\n"
        )
        env_file.chmod(0o600)
    certs = d.dir / "certs"
    info: dict[str, str] = {}
    if not (certs / "server.pem").exists():
        info = dev_certs(certs)
    state = d.dir / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    template = (d.dir / "nginx.conf.template").read_text()
    (state / "nginx.conf").write_text(template.replace("@PREFIX@", prefix))
    c1_env = state / "c1.env"
    if not c1_env.exists():
        c1_env.write_text("# Written by c1-admin bootstrap\nC1_FGA_STORE=\nC1_FGA_MODEL=\n")
    return info


def bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(Path(args.dir), args.project, {"C1_REF_NET_PREFIX": args.net_prefix})
    state = d.dir / "state" / "bootstrap.json"
    if state.exists():
        raise HostError("already bootstrapped (state/bootstrap.json exists)")
    info = prepare(d, args.net_prefix)
    d.compose("up", "-d", *BACKENDS)
    d.wait_healthy(HEALTHY)
    flags = ["bootstrap", "--admin-user", args.admin_user]
    if args.no_temporary_password:
        flags.append("--no-temporary-password")
    result = d.internal(*flags)
    (d.dir / "state" / "c1.env").write_text(
        "# Written by c1-admin bootstrap; identifiers only, no secrets.\n"
        f"C1_FGA_STORE={result['fga_store']}\nC1_FGA_MODEL={result['fga_model']}\n"
    )
    result.pop("_exit", None)
    state.write_text(json.dumps({**result, **info}, indent=2, sort_keys=True) + "\n")
    d.compose("up", "-d", "c1", "proxy")
    d.wait_healthy(("c1",))
    return {**result, **info}


def _stop_writer(d: Deployment) -> None:
    d.compose("stop", "c1")


def _terminus_volume(d: Deployment) -> str:
    name = d.container("terminusdb")
    volume = (
        d.run(
            [
                d.engine,
                "inspect",
                name,
                "--format",
                '{{range .Mounts}}{{if eq .Destination "/app/terminusdb/storage"}}'
                "{{.Name}}{{end}}{{end}}",
            ]
        )
        .stdout.decode()
        .strip()
    )
    if not volume:
        raise HostError("TerminusDB storage volume not found")
    return volume


def _export_terminus(d: Deployment, target: Path) -> None:
    """Cold copy of the whole TerminusDB storage: stop, export the volume, start.

    `terminusdb bundle` is not self-contained across servers (it references
    layers that exist only on the source server; W1 finding), so backups use
    the storage volume, and knowledge-only restores clone from it.
    """
    volume = _terminus_volume(d)
    d.compose("stop", "terminusdb")
    try:
        d.run([d.engine, "volume", "export", volume, "--output", str(target)])
    finally:
        d.compose("start", "terminusdb")
        d.wait_healthy(("terminusdb",))
    target.chmod(0o600)


def backup(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(Path(args.dir), args.project, {"C1_REF_NET_PREFIX": args.net_prefix})
    target = Path(args.to).resolve()
    if target.exists() and any(target.iterdir()):
        raise HostError("backup directory must be new or empty")
    started = time.monotonic()
    _stop_writer(d)
    try:
        state = d.internal("state")
        if state["pending_operations"]:
            raise HostError("pending security operation; recover before backup")
        target.mkdir(parents=True, mode=0o700, exist_ok=True)
        target.chmod(0o700)
        files: dict[str, str] = {}
        storage = target / "terminusdb-storage.tar"
        _export_terminus(d, storage)
        files[storage.name] = _sha256(storage)
        if not args.knowledge_only:
            pg = d.container("postgres")
            for database in ("openfga", "keycloak"):
                dump = d.run(
                    [d.engine, "exec", pg, "pg_dump", "-U", "c1", "--format=custom", database]
                ).stdout
                out = target / f"{database}.pgdump"
                out.write_bytes(dump)
                out.chmod(0o600)
                files[out.name] = _sha256(out)
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "type": "knowledge" if args.knowledge_only else "full",
            "created_at": datetime.now(UTC).isoformat(),
            "operator": _operator(args),
            "project": d.project,
            "knowledge_database": state["knowledge_database"],
            "workflow_database": state["workflow_database"],
            "knowledge_head": state["knowledge_head"],
            "workflow_head": state["workflow_head"],
            "profiles": state["profiles"],
            "fga_store": state["fga_store"],
            "fga_model": state["fga_model"],
            "files": files,
        }
        path = target / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)
    finally:
        if not args.leave_stopped:
            d.compose("start", "c1")
    sizes = {name: (target / name).stat().st_size for name in files}
    return {
        "backup": str(target),
        "manifest_sha256": _sha256(target / "manifest.json"),
        "sizes": sizes,
        "seconds": round(time.monotonic() - started, 1),
    }


def load_manifest(source: Path) -> dict[str, Any]:
    path = source / "manifest.json"
    if not path.is_file():
        raise HostError("no manifest.json; the backup is incomplete")
    manifest: dict[str, Any] = json.loads(path.read_text())
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise HostError("unsupported backup manifest version")
    for name, digest in manifest["files"].items():
        if not (source / name).is_file() or _sha256(source / name) != digest:
            raise HostError(f"backup file {name} is missing or altered")
    return manifest


def _restore_source(d: Deployment, storage: Path, prefix: str) -> tuple[str, str]:
    """A temporary, unpublished TerminusDB serving the backup's storage."""
    tag = f"{d.project}-restore-src-{int(time.time())}"
    d.run([d.engine, "volume", "create", tag])
    d.run([d.engine, "volume", "import", tag, str(storage)])
    image = (
        d.run([d.engine, "inspect", d.container("terminusdb"), "--format", "{{.ImageName}}"])
        .stdout.decode()
        .strip()
    )
    secret = d.dir / "secrets" / "terminus_password"
    d.run(
        [
            d.engine,
            "run",
            "-d",
            "--name",
            tag,
            "--network",
            f"{d.project}_backend",
            "--ip",
            f"{prefix}.40",
            "-v",
            f"{tag}:/app/terminusdb/storage",
            "-v",
            f"{secret}:/run/secrets/terminus_password:ro",
            "-e",
            "TERMINUSDB_SERVER_PORT=6363",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            'TERMINUSDB_ADMIN_PASS="$(cat /run/secrets/terminus_password)" '
            "exec /app/terminusdb/init_docker.sh",
        ]
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        probe = d.run(
            [
                d.engine,
                "exec",
                tag,
                "swipl",
                "-q",
                "-g",
                "use_module(library(http/http_open)),setup_call_cleanup(http_open("
                "'http://127.0.0.1:6363/api/ok',S,[timeout(3)]),read_string(S,_,_),close(S)),halt",
            ],
            check=False,
        )
        if probe.returncode == 0:
            return tag, f"http://{prefix}.40:6363"
        time.sleep(2)
    _drop_source(d, tag)
    raise HostError("temporary restore source did not start")


def _drop_source(d: Deployment, tag: str) -> None:
    d.run([d.engine, "rm", "-f", tag], check=False)
    d.run([d.engine, "volume", "rm", "-f", tag], check=False)


def restore_knowledge(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(Path(args.dir), args.project, {"C1_REF_NET_PREFIX": args.net_prefix})
    source = Path(args.from_).resolve()
    manifest = load_manifest(source)
    started = time.monotonic()
    _stop_writer(d)
    tag = ""
    try:
        state = d.internal("state")
        if state["pending_operations"]:
            raise HostError("pending security operation; recover before restoring")
        if state["knowledge_database"] != manifest["knowledge_database"]:
            raise HostError("backup is for a different knowledge database")
        changed = sorted(
            name
            for name, version in manifest["profiles"].items()
            if state["profiles"].get(name) != version
        )
        extra = sorted(set(state["profiles"]) - set(manifest["profiles"]))
        if changed:
            raise HostError("backup profile versions differ from the installed schema")
        if extra:
            raise HostError(
                "profiles installed after the backup: "
                + ", ".join(extra)
                + "; restore refused (reinstall them through a ChangeSet after restoring)"
            )
        safety = source.parent / f"{source.name}-safety-{int(time.time())}"
        safety.mkdir(mode=0o700)
        _export_terminus(d, safety / "terminusdb-storage.tar")
        tag, url = _restore_source(d, source / "terminusdb-storage.tar", args.net_prefix)
        cloned = d.internal("knowledge-clone", "--source-url", url)
        if cloned["knowledge_head"] != manifest["knowledge_head"]:
            raise HostError("restored knowledge head does not match the backup")
        record = d.internal(
            "record-restore",
            "--manifest-sha256",
            _sha256(source / "manifest.json"),
            "--previous-head",
            state["knowledge_head"],
            "--restored-head",
            manifest["knowledge_head"],
            "--operator",
            _operator(args),
        )
    finally:
        if tag:
            _drop_source(d, tag)
        d.compose("start", "c1")
    return {
        "restored_head": manifest["knowledge_head"],
        "previous_head": state["knowledge_head"],
        "safety_copy": str(safety),
        "restore_record": record["restore_record"],
        "seconds": round(time.monotonic() - started, 1),
    }


def restore_full(args: argparse.Namespace) -> dict[str, Any]:
    """Restore everything into a fresh, isolated deployment that stays guarded."""
    source = Path(args.from_).resolve()
    manifest = load_manifest(source)
    if manifest["type"] != "full":
        raise HostError("a full restore needs a full backup")
    origin = Path(args.dir).resolve()
    target_dir = Path(args.target_dir).resolve()
    if target_dir.exists():
        raise HostError("target directory must not exist")
    target_dir.mkdir(parents=True, mode=0o700)
    for name in ("compose.yaml", "nginx.conf.template", "postgres-init.sh"):
        shutil.copy2(origin / name, target_dir / name)
    # Secrets and certificates come from the operator's own secret backup; on
    # one host the source deployment's files are that backup.
    shutil.copytree(origin / "secrets", target_dir / "secrets")
    shutil.copytree(origin / "certs", target_dir / "certs")
    d = Deployment(
        target_dir,
        args.target_project,
        {"C1_REF_NET_PREFIX": args.target_net_prefix, "C1_REF_PORT": args.target_port},
    )
    existing = (
        d.run(
            [
                d.engine,
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={d.project}",
                "--format",
                "{{.Names}}",
            ]
        )
        .stdout.decode()
        .split()
    )
    volumes = d.run([d.engine, "volume", "ls", "--format", "{{.Name}}"]).stdout.decode().split()
    if existing or any(v.startswith(f"{d.project}_") for v in volumes):
        raise HostError("target project already has containers or volumes")
    prepare(d, args.target_net_prefix)
    (target_dir / "state" / "c1.env").write_text(
        "# Restored from backup manifest; identifiers only.\n"
        f"C1_FGA_STORE={manifest['fga_store']}\nC1_FGA_MODEL={manifest['fga_model']}\n"
    )
    started = time.monotonic()
    storage_volume = f"{d.project}_terminus-data"
    d.run([d.engine, "volume", "create", storage_volume])
    d.run([d.engine, "volume", "import", storage_volume, str(source / "terminusdb-storage.tar")])
    d.compose("up", "-d", "postgres", "terminusdb")
    d.wait_healthy(("postgres", "terminusdb"))
    pg = d.container("postgres")
    for database, owner in (("openfga", "openfga"), ("keycloak", "keycloak")):
        d.run(
            [
                d.engine,
                "exec",
                "-i",
                pg,
                "pg_restore",
                "-U",
                "c1",
                "-d",
                database,
                "--clean",
                "--if-exists",
                "--no-owner",
                f"--role={owner}",
            ],
            input=(source / f"{database}.pgdump").read_bytes(),
        )
    d.compose("up", "-d", "openfga-migrate", "openfga", "keycloak")
    d.wait_healthy(("openfga", "keycloak"))
    state = d.internal("state")
    if (state["knowledge_head"], state["workflow_head"]) != (
        manifest["knowledge_head"],
        manifest["workflow_head"],
    ):
        raise HostError("restored database heads do not match the backup manifest")
    guard = d.internal(
        "guard-set",
        "--manifest-sha256",
        _sha256(source / "manifest.json"),
        "--operator",
        _operator(args),
    )
    d.compose("up", "-d", "c1")
    d.wait_healthy(("c1",))
    return {
        "target_project": d.project,
        "guard": guard["guard"],
        "seconds": round(time.monotonic() - started, 1),
        "next": "c1-admin dr verify, then c1-admin dr release; the proxy starts on release",
    }


def dr_verify(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(Path(args.dir), args.project, {"C1_REF_NET_PREFIX": args.net_prefix})
    return d.internal("dr-verify")


def dr_release(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(
        Path(args.dir),
        args.project,
        {"C1_REF_NET_PREFIX": args.net_prefix, "C1_REF_PORT": args.port},
    )
    result = d.internal(
        "dr-release",
        "--accept-security-as-of",
        args.accept_security_as_of,
        "--reason",
        args.reason,
        "--operator",
        _operator(args),
    )
    # The guard is read at startup, so the service must really restart.
    # `restart` refuses while a dependency (the one-shot migration) has exited.
    d.run([d.engine, "stop", d.container("c1")])
    d.run([d.engine, "start", d.container("c1")])
    d.wait_healthy(("c1",))
    d.compose("up", "-d", "proxy")
    return result


def consistency(args: argparse.Namespace) -> dict[str, Any]:
    d = Deployment(Path(args.dir), args.project, {"C1_REF_NET_PREFIX": args.net_prefix})
    return d.internal("consistency")


def certs(args: argparse.Namespace) -> dict[str, Any]:
    return dev_certs(Path(args.out))


def build_parser(sub: Any) -> None:
    def common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dir", default="deployment/reference")
        parser.add_argument("--project", default="c1-ref")
        parser.add_argument("--net-prefix", default="10.89.251")
        parser.add_argument("--operator")

    boot = sub.add_parser("bootstrap", help="first start of an empty deployment")
    common(boot)
    boot.add_argument("--admin-user", default="c1admin")
    boot.add_argument("--no-temporary-password", action="store_true")
    back = sub.add_parser("backup", help="quiesced knowledge and security backup")
    common(back)
    back.add_argument("--to", required=True)
    back.add_argument("--knowledge-only", action="store_true")
    back.add_argument("--leave-stopped", action="store_true")
    rk = sub.add_parser("restore-knowledge", help="replace knowledge; keep current security")
    common(rk)
    rk.add_argument("--from", dest="from_", required=True)
    rf = sub.add_parser("restore-full", help="restore everything into an isolated deployment")
    common(rf)
    rf.add_argument("--from", dest="from_", required=True)
    rf.add_argument("--target-dir", required=True)
    rf.add_argument("--target-project", default="c1-dr")
    rf.add_argument("--target-net-prefix", default="10.89.252")
    rf.add_argument("--target-port", default="18444")
    dr = sub.add_parser("dr", help="disaster-recovery verification and release")
    drs = dr.add_subparsers(dest="dr_command", required=True)
    verify = drs.add_parser("verify")
    common(verify)
    release = drs.add_parser("release")
    common(release)
    release.add_argument("--port", default="18443")
    release.add_argument("--accept-security-as-of", required=True)
    release.add_argument("--reason", required=True)
    check = sub.add_parser("consistency", help="compare journal bindings with OpenFGA")
    common(check)
    dev = sub.add_parser("dev-certs", help="throwaway test CA and server certificate")
    dev.add_argument("--out", required=True)


HANDLERS = {
    "bootstrap": bootstrap,
    "backup": backup,
    "restore-knowledge": restore_knowledge,
    "restore-full": restore_full,
    "consistency": consistency,
    "dev-certs": certs,
}


def run(args: argparse.Namespace) -> int:
    handler = HANDLERS.get(args.command)
    if args.command == "dr":
        handler = dr_verify if args.dr_command == "verify" else dr_release
    assert handler is not None
    try:
        result = handler(args)
    except HostError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    exit_code = int(result.pop("_exit", 0)) if isinstance(result, dict) else 0
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code
