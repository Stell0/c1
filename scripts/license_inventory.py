"""Third-party license inventory and notices for the release candidate (M13 D13).

Modes:
  (default)   regenerate docs/release/third-party.json and THIRD_PARTY_NOTICES
              from the locked runtime dependencies and the recorded license files;
  --extract   copy license files out of the pinned service images into
              docs/release/licenses/ (needs the container engine and the images);
  --os        record the OS packages of the C1 runtime image and the proxy image
              into docs/release/os-packages.json (needs the built image);
  --check     regenerate in memory and fail if any committed output differs, or a
              runtime distribution lacks a license file or has a disallowed license.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "docs/release"
LICENSES = RELEASE / "licenses"
INVENTORY = RELEASE / "third-party.json"
OS_PACKAGES = RELEASE / "os-packages.json"
NOTICES = ROOT / "THIRD_PARTY_NOTICES"
DISALLOWED = ("AGPL", "SSPL", "BUSL", "Commons-Clause", "Proprietary", "Elastic-2.0")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def runtime_distributions() -> list[tuple[str, str]]:
    """The exact runtime set of uv.lock (no dev group, no project)."""
    output = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--format",
            "requirements-txt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result = []
    for line in output.splitlines():
        line = line.split(";")[0].strip()
        if line and not line.startswith(("#", "-")) and "==" in line:
            name, version = line.split("==", 1)
            result.append((name.strip(), version.strip()))
    return sorted(result, key=lambda item: item[0].lower())


def python_entries() -> list[dict[str, Any]]:
    entries = []
    for name, version in runtime_distributions():
        dist = metadata.distribution(name)
        if dist.version != version:
            raise SystemExit(f"{name}: installed {dist.version}, locked {version}; run uv sync")
        meta = dist.metadata
        expression = meta.get("License-Expression") or ""
        classifiers = sorted(
            c for c in (meta.get_all("Classifier") or []) if c.startswith("License")
        )
        files = []
        for file in dist.files or []:
            upper = file.name.upper()
            if any(word in upper for word in ("LICEN", "COPYING", "NOTICE", "AUTHORS")):
                data = Path(file.locate()).read_bytes()
                files.append(
                    {
                        "path": str(file),
                        "sha256": _sha(data),
                        "text": data.decode("utf-8", "replace"),
                    }
                )
        entries.append(
            {
                "name": meta["Name"],
                "version": dist.version,
                "license_expression": expression,
                "license_classifiers": classifiers,
                "license_files": sorted(files, key=lambda f: f["path"]),
            }
        )
    return entries


def image_entries() -> list[dict[str, Any]]:
    entries = []
    for source in (ROOT / "deployment/images.json", ROOT / "deployment/reference/images.json"):
        for key, item in json.loads(source.read_text()).items():
            files = []
            for path in sorted(LICENSES.glob(f"{key}--*")):
                files.append(
                    {"file": str(path.relative_to(ROOT)), "sha256": _sha(path.read_bytes())}
                )
            entries.append(
                {
                    "key": key,
                    "image": item["image"],
                    "tag": item["tag"],
                    "digest": item.get("platform_digest") or item.get("digest"),
                    "license": item["license"],
                    "role": item.get("role", "service of the reference and development stacks"),
                    "license_files": files,
                }
            )
    return entries


def extract() -> None:
    LICENSES.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "deployment/images.json", ROOT / "deployment/reference/images.json"):
        for key, item in json.loads(source.read_text()).items():
            artifact = item.get("license_artifact")
            if artifact:
                # M01 already extracted and hash-pinned this file from the image.
                data = (ROOT / "docs/evidence/M01/licenses" / artifact).read_bytes()
                if _sha(data) != item["license_sha256"]:
                    raise SystemExit(f"{key}: M01 license artifact does not match images.json")
                (LICENSES / f"{key}--{artifact}").write_bytes(data)
                continue
            digest = item.get("platform_digest") or item.get("digest")
            ref = f"{item['image']}@{digest}"
            paths = (
                item.get("license_paths")
                or [p for p in item.get("embedded_license_paths", [])[:1]]
                + item.get("embedded_notice_paths", [])[:1]
            )
            name = subprocess.run(
                ["podman", "create", ref], capture_output=True, text=True, check=True
            ).stdout.strip()
            try:
                for inside in paths:
                    target = LICENSES / f"{key}--{Path(inside).name}"
                    done = subprocess.run(
                        ["podman", "cp", f"{name}:{inside}", str(target)], capture_output=True
                    )
                    if done.returncode == 0:
                        target.chmod(0o644)
            finally:
                subprocess.run(["podman", "rm", "-f", name], capture_output=True)


def os_packages(image: str) -> None:
    result: dict[str, Any] = {}
    debian = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--entrypoint",
            "dpkg-query",
            image,
            "-W",
            "-f",
            "${Package}\t${Version}\n",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result["c1-runtime (Debian)"] = sorted(line.split("\t") for line in debian.splitlines() if line)
    nginx = json.loads((ROOT / "deployment/reference/images.json").read_text())["nginx"]
    alpine = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--entrypoint",
            "apk",
            f"{nginx['image']}@{nginx['platform_digest']}",
            "list",
            "--installed",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result["nginx (Alpine)"] = sorted(line.split(" [")[0] for line in alpine.splitlines() if line)
    OS_PACKAGES.write_text(json.dumps(result, indent=2) + "\n")


def notices(inventory: dict[str, Any]) -> str:
    lines = [
        "C1 THIRD-PARTY NOTICES",
        "======================",
        "",
        "Generated by scripts/license_inventory.py from uv.lock, deployment/images.json and",
        "deployment/reference/images.json. C1 itself is licensed under Apache-2.0 (LICENSE).",
        "",
        "Part 1 lists the Python distributions installed in the C1 runtime image, with their",
        "license texts. Part 2 lists the container images that the reference deployment runs by",
        "digest; their license files are in docs/release/licenses/. Part 3 describes the",
        "operating-system packages of the base images (docs/release/os-packages.json).",
        "",
        "PART 1 - Python runtime distributions",
        "--------------------------------------",
    ]
    for entry in inventory["python"]:
        licence = (
            entry["license_expression"] or "; ".join(entry["license_classifiers"]) or "see files"
        )
        lines += ["", f"{entry['name']} {entry['version']}  ({licence})"]
        for file in entry["license_files"]:
            lines += [f"--- {file['path']} ---", file["text"].rstrip(), ""]
    lines += ["", "PART 2 - Container images", "-------------------------"]
    for entry in inventory["images"]:
        lines += [
            "",
            f"{entry['image']}:{entry['tag']}",
            f"  digest: {entry['digest']}",
            f"  license: {entry['license']}",
            f"  role: {entry['role']}",
        ]
        for file in entry["license_files"]:
            lines.append(f"  license file: {file['file']} ({file['sha256']})")
    lines += [
        "",
        "PART 3 - Operating-system packages",
        "----------------------------------",
        "",
        "The C1 runtime image is based on docker.io/library/python:3.13-slim (Debian). The",
        "proxy image is docker.io/library/nginx:stable-alpine (Alpine). Their OS packages keep",
        "their own licenses; each Debian package's terms are in /usr/share/doc/<package>/copyright",
        "inside the image, and Alpine package licenses are listed by `apk list --installed`.",
        "The package lists recorded for this release are in docs/release/os-packages.json.",
        "",
    ]
    return "\n".join(lines)


def build() -> tuple[dict[str, Any], str]:
    inventory = {"python": python_entries(), "images": image_entries()}
    serial = {
        "python": [
            {k: v for k, v in e.items() if k != "license_files"}
            | {
                "license_files": [
                    {k: v for k, v in f.items() if k != "text"} for f in e["license_files"]
                ]
            }
            for e in inventory["python"]
        ],
        "images": inventory["images"],
    }
    return serial, notices(inventory)


def policy(serial: dict[str, Any]) -> list[str]:
    problems = []
    for entry in serial["python"]:
        text = " ".join([entry["license_expression"], *entry["license_classifiers"]])
        if not entry["license_files"]:
            problems.append(f"{entry['name']}: no license file installed")
        if any(word.lower() in text.lower() for word in DISALLOWED):
            problems.append(f"{entry['name']}: disallowed license {text}")
    for entry in serial["images"]:
        if any(word.lower() in entry["license"].lower() for word in DISALLOWED):
            problems.append(f"{entry['image']}: disallowed license")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--os", metavar="C1_IMAGE")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.extract:
        extract()
    if args.os:
        os_packages(args.os)
    serial, text = build()
    problems = policy(serial)
    rendered = json.dumps(serial, indent=2, sort_keys=True) + "\n"
    if args.check:
        if INVENTORY.read_text() != rendered:
            problems.append("docs/release/third-party.json is out of date")
        if NOTICES.read_text() != text:
            problems.append("THIRD_PARTY_NOTICES is out of date")
        for entry in serial["images"]:
            for file in entry["license_files"]:
                if _sha((ROOT / file["file"]).read_bytes()) != file["sha256"]:
                    problems.append(f"{file['file']} changed")
    else:
        RELEASE.mkdir(parents=True, exist_ok=True)
        INVENTORY.write_text(rendered)
        NOTICES.write_text(text)
    for problem in problems:
        print("license-inventory:", problem, file=sys.stderr)
    print(
        f"python distributions: {len(serial['python'])}; images: {len(serial['images'])}; "
        f"problems: {len(problems)}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
