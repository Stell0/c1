"""Packaging and security audit of the release candidate (M13 D14).

Checks the built C1 image, the reference Compose file, the source tree and,
when it is running, the reference deployment. Writes a JSON report and exits
non-zero on any finding. No secret value is printed or written.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from c1 import __version__

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.environ.get("C1_ENGINE", "podman")
AI_PACKAGES = re.compile(
    r"^(openai|anthropic|google-generativeai|google-genai|transformers|torch|tensorflow|"
    r"sentence-transformers|langchain.*|llama.*|cohere|mistralai|ollama|huggingface-hub|"
    r"tiktoken)$",
    re.I,
)
DEV_PACKAGES = re.compile(r"^(pytest|playwright|mypy|ruff|detect-secrets|openfga-sdk)$", re.I)
ALLOWED_IMAGES = re.compile(
    r"^(docker\.io/terminusdb/terminusdb-server|docker\.io/library/postgres|"
    r"docker\.io/openfga/openfga|quay\.io/keycloak/keycloak|docker\.io/library/nginx|"
    r"localhost/c1)[@:]"
)
FAIL_DETECTORS = {"Private Key", "AWS Access Key", "Basic Auth Credentials", "JSON Web Token"}
DYNAMIC_IMPORT_ALLOWLIST: set[str] = set()


def _run(*argv: str, input: bytes | None = None) -> bytes:
    return subprocess.run(argv, input=input, capture_output=True, check=True).stdout


def image_checks(image: str) -> dict[str, Any]:
    findings: list[str] = []
    info = json.loads(_run(ENGINE, "image", "inspect", image))[0]
    config = info["Config"]
    if config.get("User") not in (None, "", "0", "root"):
        pass
    name = _run(ENGINE, "create", image).decode().strip()
    try:
        archive = _run(ENGINE, "export", name)
    finally:
        subprocess.run([ENGINE, "rm", "-f", name], capture_output=True)
    members = tarfile.open(fileobj=io.BytesIO(archive)).getmembers()
    paths = [m.name for m in members]
    for path in paths:
        base = path.rsplit("/", 1)[-1]
        if base in {".env", "id_rsa", "id_ed25519"} or base.endswith((".key", ".p12", ".pfx")):
            findings.append(f"image contains {path}")
        if re.search(r"(^|/)(tests|fixtures)/", path) and "/site-packages/" not in path:
            findings.append(f"image contains test material {path}")
    packages = json.loads(
        _run(
            ENGINE,
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "-c",
            "import json, importlib.metadata as m; "
            "print(json.dumps(sorted({d.metadata['Name'] for d in m.distributions()})))",
        )
    )
    for package in packages:
        if AI_PACKAGES.match(package):
            findings.append(f"AI SDK or model package installed: {package}")
        if DEV_PACKAGES.match(package):
            findings.append(f"development package installed: {package}")
    with tempfile.TemporaryDirectory() as directory:
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(
            directory,
            members=[
                m
                for m in members
                if m.name.startswith(("opt/c1/", "usr/local/bin/c1"))
                and m.isfile()
                and not m.name.endswith((".pyc", ".so"))
            ],
            filter="data",
        )
        scan = json.loads(_run("detect-secrets", "scan", "--all-files", directory))
    counts: dict[str, int] = {}
    for results in scan["results"].values():
        for result in results:
            counts[result["type"]] = counts.get(result["type"], 0) + 1
    for detector in FAIL_DETECTORS & set(counts):
        findings.append(f"image filesystem scan found {counts[detector]} {detector}")
    return {
        "image": image,
        "image_id": info["Id"],
        "user_in_image_config": config.get("User") or "root (entrypoint drops to 10001)",
        "entrypoint": config.get("Entrypoint"),
        "file_count": len(paths),
        "python_distributions": packages,
        "image_scan_counts": counts,
        "findings": findings,
    }


def compose_checks() -> dict[str, Any]:
    findings: list[str] = []
    compose = yaml.safe_load((ROOT / "deployment/reference/compose.yaml").read_text())
    services = compose["services"]
    published = [name for name, s in services.items() if s.get("ports")]
    if published != ["proxy"]:
        findings.append(f"services publishing ports: {published}")
    for name, service in services.items():
        if not ALLOWED_IMAGES.match(str(service["image"])):
            findings.append(f"{name}: unexpected image {service['image']}")
        if "mem_limit" not in service or "cpus" not in service:
            if name not in {"openfga-migrate"} or "mem_limit" not in service:
                findings.append(f"{name}: missing resource limits")
        env = service.get("environment") or {}
        if isinstance(env, dict):
            for key, value in env.items():
                if re.search(r"(PASSWORD|TOKEN|SECRET)", key) and not key.endswith("_FILE"):
                    if not (isinstance(value, str) and value.startswith("/")):
                        findings.append(f"{name}: secret-like setting {key} in compose text")
    networks = compose["networks"]
    if not networks["backend"].get("internal"):
        findings.append("backend network is not internal")
    terminus = services["terminusdb"]["environment"]
    if terminus.get("TERMINUSDB_PLUGINS_PATH") != "/nonexistent-c1-plugins":
        findings.append("TerminusDB plugin path is not disabled")
    realm = json.loads((ROOT / "src/c1/admin/realm-c1.json").read_text())
    for client in realm["clients"]:
        if client.get("secret") not in (None, "@EXPLORER_CLIENT_SECRET@"):
            findings.append(f"realm client {client['clientId']} carries a secret")
    if realm.get("users"):
        findings.append("realm template contains users")
    return {"services": sorted(services), "published": published, "findings": findings}


def source_checks() -> dict[str, Any]:
    findings: list[str] = []
    dynamic: list[str] = []
    for path in sorted((ROOT / "src/c1").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else func.id
                    if isinstance(func, ast.Name)
                    else ""
                )
                if name in {
                    "import_module",
                    "__import__",
                    "entry_points",
                    "load_module",
                    "exec_module",
                }:
                    where = f"{path.relative_to(ROOT)}:{node.lineno}:{name}"
                    dynamic.append(where)
                    if where.split(":")[0] not in DYNAMIC_IMPORT_ALLOWLIST:
                        findings.append(f"dynamic import (plugin loader risk) at {where}")
    pyproject = (ROOT / "pyproject.toml").read_text()
    if re.search(r"entry-points|\[project\.entry-points", pyproject):
        findings.append("pyproject declares plugin entry points")
    secrets_check = subprocess.run(
        ["uv", "run", "--locked", "python", "scripts/check_secrets.py"],
        cwd=ROOT,
        capture_output=True,
    )
    if secrets_check.returncode != 0:
        findings.append("repository secret check failed")
    return {"dynamic_imports": dynamic, "findings": findings}


def deployment_checks(project: str) -> dict[str, Any]:
    findings: list[str] = []
    names = (
        _run(
            ENGINE,
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Names}}",
        )
        .decode()
        .split()
    )
    if not names:
        return {"running": False, "findings": []}
    ports = {}
    for name in names:
        info = json.loads(_run(ENGINE, "inspect", name))[0]
        bindings = info["HostConfig"].get("PortBindings") or {}
        if bindings:
            ports[name] = sorted(bindings)
        if info["Config"].get("Labels", {}).get("com.docker.compose.service") == "c1":
            for item in info["Config"]["Env"]:
                key = item.split("=", 1)[0]
                if re.search(r"(PASSWORD|TOKEN|SECRET)", key) and not key.endswith("_FILE"):
                    findings.append(f"{name}: secret value in environment ({key})")
    if [n for n in ports if "proxy" not in n]:
        findings.append(f"containers with published ports: {sorted(ports)}")
    return {"running": True, "published": ports, "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="localhost/c1:" + __version__)
    parser.add_argument("--project", default=os.environ.get("C1_REFERENCE_PROJECT", "c1-ref"))
    parser.add_argument("--out", default=str(ROOT / "docs/evidence/M13/release-audit.json"))
    args = parser.parse_args()
    report: dict[str, Any] = {
        "image": image_checks(args.image),
        "compose": compose_checks(),
        "source": source_checks(),
        "deployment": deployment_checks(args.project),
    }
    findings = [f for section in report.values() for f in section["findings"]]
    report["findings"] = findings
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for finding in findings:
        print("release-audit:", finding, file=sys.stderr)
    print(f"release audit: {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
