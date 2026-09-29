"""Verify a SHA-256 manifest against the current source-input inventory."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = Path(__file__).with_name("implementation-files.sha256")
SOURCE_ROOTS = ("src", "scripts", "tests", "profiles", "fixtures", "probes", "deployment")
ROOT_INPUTS = {"Makefile", "pyproject.toml", "uv.lock", "compose.yaml", ".secrets.baseline"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def private_dotenv(name: str) -> bool:
    """Exclude dotenv files by name without opening or hashing them."""
    basename = PurePosixPath(name).name
    return basename.startswith(".env") and basename != ".env.example"


def is_source_input(name: str) -> bool:
    path = PurePosixPath(name)
    if private_dotenv(name):
        return False
    return name in ROOT_INPUTS or path.parts[0] in SOURCE_ROOTS


def source_inventory() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        name
        for name in (os.fsdecode(item) for item in result.stdout.split(b"\0") if item)
        if is_source_input(name)
    }


def read_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read manifest: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        digest, separator, name = line.partition("  ")
        relative = PurePosixPath(name)
        if (
            not separator
            or not SHA256_RE.fullmatch(digest)
            or not name
            or relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or "\\" in name
            or name in entries
            or private_dotenv(name)
        ):
            raise ValueError(f"invalid or duplicate manifest entry on line {line_number}")
        entries[name] = digest
    return entries


def sha256_input(name: str) -> str:
    path = ROOT.joinpath(*PurePosixPath(name).parts)
    if path.is_symlink():
        data = os.fsencode(os.readlink(path))
    elif path.is_file():
        data = path.read_bytes()
    else:
        raise FileNotFoundError(name)
    return hashlib.sha256(data).hexdigest()


def verify(manifest_path: Path) -> list[str]:
    entries = read_manifest(manifest_path)
    actual = source_inventory()
    problems: list[str] = []

    missing = sorted(actual - entries.keys())
    unexpected = sorted(entries.keys() - actual)
    if missing:
        problems.append(f"missing manifest inputs ({len(missing)}): " + ", ".join(missing))
    if unexpected:
        problems.append("unexpected manifest inputs: " + ", ".join(unexpected))

    for name in sorted(actual & entries.keys()):
        try:
            digest = sha256_input(name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot hash input {name}: {exc}")
            continue
        if digest != entries[name]:
            problems.append(f"changed input: {name}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        help="manifest path (relative paths are resolved from the repository root)",
    )
    args = parser.parse_args()
    manifest = args.manifest or DEFAULT_MANIFEST
    if not manifest.is_absolute():
        manifest = ROOT / manifest

    try:
        problems = verify(manifest)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    count = len(read_manifest(manifest))
    display_path = manifest.relative_to(ROOT) if manifest.is_relative_to(ROOT) else manifest
    print(f"PASS: {count} current source inputs match {display_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
