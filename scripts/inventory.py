"""Inventory the installed M01 images and locked Python packages without network access."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import uuid
from importlib import metadata
from pathlib import Path
from typing import Any

from probes.config import ROOT, runtime

MANIFEST = ROOT / "deployment/images.json"
EVIDENCE = ROOT / "docs/evidence/M01"
LICENSES = EVIDENCE / "licenses"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        # Runtime diagnostics can include environment-specific details; do not persist them.
        raise RuntimeError(f"Inventory command failed: {args[0]} {args[1]} ({result.returncode})")
    return result.stdout.strip()


def _probe_container_files(image: str, paths: list[str]) -> dict[str, str]:
    """Read candidate files from an unstarted, uniquely named test container."""
    name = "c1-dev-inventory-" + uuid.uuid4().hex[:16]
    _command(runtime(), "create", "--name", name, image)
    found: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="c1-m01-inventory-") as directory:
            for index, path in enumerate(paths):
                if not path.startswith("/") or ".." in Path(path).parts:
                    raise ValueError("Invalid image evidence path")
                destination = Path(directory) / str(index)
                result = subprocess.run(
                    [runtime(), "cp", f"{name}:{path}", str(destination)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    if not destination.is_file():
                        raise RuntimeError("Image evidence path is not a regular file")
                    found[path] = _digest(destination.read_bytes())
    finally:
        _command(runtime(), "rm", "-f", name)
    return found


def _image_inventory(name: str, item: dict[str, Any]) -> dict[str, Any]:
    image = str(item["image"])
    index_digest = str(item["digest"])
    reference = image + "@" + index_digest
    # Format at the runtime boundary so image Config.Env never enters inventory data.
    engine = runtime()
    docker = Path(engine).name == "docker"
    inspected = _command(
        engine,
        "image",
        "inspect",
        "--format",
        "{{.Id}}\t"
        + ("docker" if docker else "{{.Digest}}")
        + "\t{{json .RepoDigests}}\t{{.Os}}\t{{.Architecture}}",
        reference,
    ).split("\t")
    if len(inspected) != 5:
        raise RuntimeError(f"Unexpected image inspection fields: {name}")
    image_id, actual_index, digest_json, image_os, architecture = inspected
    repo_digests = set(json.loads(digest_json))
    expected = {reference, image + "@" + str(item["platform_digest"])}
    if docker:
        # Docker's containerd image store reports the index as Id and omits
        # Digest. Verify the actual local OCI content, without reading Config.Env
        # into diagnostic output or fetching mutable registry metadata.
        normalized = {
            value.removeprefix("docker.io/").removeprefix("library/") for value in repo_digests
        }
        if reference.removeprefix("docker.io/").removeprefix("library/") not in normalized:
            raise RuntimeError(f"Image index digest mismatch: {name}")
        with tempfile.TemporaryDirectory(prefix="c1-image-content-") as directory:
            archive = Path(directory) / "image.tar"
            _command(engine, "image", "save", "--output", str(archive), reference)
            with tarfile.open(archive) as contents:
                for digest in (index_digest, item["platform_digest"], item["config_digest"]):
                    blob = contents.extractfile("blobs/sha256/" + digest.removeprefix("sha256:"))
                    if blob is None or _digest(blob.read()) != digest:
                        raise RuntimeError(f"Image content digest mismatch: {name}")
                manifest_blob = contents.extractfile(
                    "blobs/sha256/" + item["platform_digest"].removeprefix("sha256:")
                )
                if manifest_blob is None:
                    raise RuntimeError(f"Image platform manifest missing: {name}")
                config_digest = str(json.load(manifest_blob)["config"]["digest"])
    else:
        if not expected.issubset(repo_digests) or actual_index != index_digest:
            raise RuntimeError(f"Image index/platform digest mismatch: {name}")
        config_digest = "sha256:" + image_id.removeprefix("sha256:")
    if config_digest != item["config_digest"]:
        raise RuntimeError(f"Image config digest mismatch: {name}")
    platform = image_os + "/" + architecture
    if platform != item["platform"]:
        raise RuntimeError(f"Image platform mismatch: {name}")

    artifact_name = str(item["license_artifact"])
    if Path(artifact_name).name != artifact_name:
        raise ValueError("License artifact must be a simple filename")
    artifact = LICENSES / artifact_name
    if not artifact.is_file():
        raise RuntimeError(f"Tagged-source license file missing: {name}")
    license_hash = _digest(artifact.read_bytes())
    if license_hash != item["license_sha256"]:
        raise RuntimeError(f"Tagged-source license hash mismatch: {name}")
    license_text = artifact.read_text()
    if item["license"] == "Apache-2.0":
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise RuntimeError(f"Tagged-source license text mismatch: {name}")
    elif item["license"] == "PostgreSQL":
        if "PostgreSQL Database Management System" not in license_text:
            raise RuntimeError(f"Tagged-source license text mismatch: {name}")
    else:
        raise RuntimeError(f"Unreviewed mandatory image license: {name}")
    source_url = str(item["license_source"])
    if not source_url.startswith("https://raw.githubusercontent.com/"):
        raise RuntimeError(f"License source is not the pinned upstream URL: {name}")

    license_paths = list(item["embedded_license_paths"])
    notice_paths = list(item["embedded_notice_paths"])
    embedded = _probe_container_files(reference, list(dict.fromkeys(license_paths + notice_paths)))
    embedded_licenses = {path: embedded[path] for path in license_paths if path in embedded}
    embedded_notices = {path: embedded[path] for path in notice_paths if path in embedded}
    if embedded_licenses and license_hash not in embedded_licenses.values():
        raise RuntimeError(f"Embedded and tagged-source licenses differ: {name}")
    return {
        "image": image,
        "tag": item["tag"],
        "reference": reference,
        "index_digest": index_digest,
        "platform_digest": item["platform_digest"],
        "config_digest": config_digest,
        "platform": platform,
        "license": item["license"],
        "license_source": source_url,
        "license_artifact": str(artifact.relative_to(ROOT)),
        "license_sha256": license_hash,
        "embedded_license_paths_checked": license_paths,
        "embedded_licenses": embedded_licenses,
        "embedded_notice_paths_checked": notice_paths,
        "embedded_notices": embedded_notices,
    }


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_inventory() -> dict[str, Any]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {_normal(item["name"]): item["version"] for item in lock["package"]}
    distributions: list[dict[str, Any]] = []
    installed: set[str] = set()
    for distribution in sorted(
        metadata.distributions(), key=lambda dist: _normal(str(dist.metadata["Name"]))
    ):
        name = str(distribution.metadata["Name"])
        normalized = _normal(name)
        if normalized == "c1":
            continue
        if normalized not in locked or distribution.version != locked[normalized]:
            raise RuntimeError(f"Installed Python package differs from uv.lock: {name}")
        installed.add(normalized)
        files = distribution.files or []
        license_files = []
        notice_files = []
        for file in files:
            path = str(file)
            basename = file.name.upper()
            if basename.startswith(("LICENSE", "COPYING", "COPYRIGHT")):
                absolute = Path(str(distribution.locate_file(file)))
                if absolute.is_file():
                    license_files.append({"path": path, "sha256": _digest(absolute.read_bytes())})
            if basename.startswith("NOTICE"):
                absolute = Path(str(distribution.locate_file(file)))
                if absolute.is_file():
                    notice_files.append({"path": path, "sha256": _digest(absolute.read_bytes())})
        if not license_files:
            raise RuntimeError(f"Installed Python package has no license file: {name}")
        distributions.append(
            {
                "name": name,
                "version": distribution.version,
                "license_expression": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or "not declared",
                "license_files": license_files,
                "notice_files": notice_files,
            }
        )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    direct = list(project["project"].get("dependencies", []))
    for group in project.get("dependency-groups", {}).values():
        direct.extend(group)
    for requirement in direct:
        name = _normal(re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip())
        if name not in installed:
            raise RuntimeError(f"Direct Python dependency not installed: {name}")
    return {
        "python_version": sys.version.split()[0],
        "packages": distributions,
        "locked_but_not_installed_on_this_platform": sorted(set(locked) - installed - {"c1"}),
    }


def build_inventory() -> dict[str, Any]:
    manifest: dict[str, dict[str, Any]] = json.loads(MANIFEST.read_text())
    if set(manifest) != {"terminusdb", "openfga", "keycloak", "postgres"}:
        raise RuntimeError("Unexpected mandatory image set")
    images = {name: _image_inventory(name, item) for name, item in manifest.items()}
    return {
        "runtime": runtime(),
        "runtime_version": _command(runtime(), "--version"),
        "images": images,
        "python": _python_inventory(),
    }


def write_inventory(inventory: dict[str, Any]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    lines = [
        "# M01 artifact inventory",
        "",
        f"Runtime: `{inventory['runtime_version']}`.",
        f"Python: `{inventory['python']['python_version']}`.",
        "",
        "The repository digest is the pinned image index; the platform digest is the selected",
        "linux/amd64 manifest in the local image store. The config digest is the",
        "inspected image ID.",
        "Source-tag licenses are bundled for offline checks. Candidate image paths were checked",
        "in unstarted disposable containers; an empty embedded result means absent at those paths,",
        "not proof that the image contains no license anywhere. Notice review for redistribution",
        "remains an M13 obligation.",
        "",
        (
            "| Image | Tag | Index digest | Platform digest | Config digest | "
            "License evidence | Embedded license | Embedded notice |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, item in inventory["images"].items():
        embedded_license = ", ".join(item["embedded_licenses"]) or "none at checked paths"
        embedded_notice = ", ".join(item["embedded_notices"]) or "none at checked paths"
        lines.append(
            f"| {name} | `{item['tag']}` | `{item['index_digest']}` | "
            f"`{item['platform_digest']}` | `{item['config_digest']}` | "
            f"[{item['license']}]({item['license_source']}) "
            f"(`{item['license_artifact']}`, `{item['license_sha256']}`) | "
            f"{embedded_license} | {embedded_notice} |"
        )
    lines.extend(
        [
            "",
            "## Installed Python packages",
            "",
            "All installed non-project distributions match `uv.lock` and have an",
            "installed license file. Package versions, license hashes, and notice",
            "presence are in `inventory.json`.",
            "Packages locked but not installed on this platform: "
            + (
                ", ".join(inventory["python"]["locked_but_not_installed_on_this_platform"])
                or "none"
            )
            + ".",
            "",
        ]
    )
    (EVIDENCE / "inventory.md").write_text("\n".join(lines))


def main() -> None:
    inventory = build_inventory()
    write_inventory(inventory)
    print(
        f"M01 inventory: {len(inventory['images'])} images, "
        f"{len(inventory['python']['packages'])} installed Python packages"
    )


if __name__ == "__main__":
    main()
