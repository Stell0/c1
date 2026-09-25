"""Check the local baseline and evidence claims without network access."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

SOURCE_REVISION = (
    "ANLCKQkD89hnI-0XryiImiiO8yvhoUseyovja35ppyfl8AmQjIBn_AU-aVvDOUS0K7P60fBKlXedaakqzyvt0A"
)


def read(root: Path, name: str) -> str:
    path = root / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def requirement_errors(root: Path) -> list[str]:
    errors = []
    spec = read(root, "PROJECT_SPECIFICATION.md")
    architecture = read(root, "MVP_ARCHITECTURE.md")
    # F05 and F06 are section headings, while the other F IDs have subsections.
    for prefix, count, name, content in (
        ("F", 10, "PROJECT_SPECIFICATION.md", spec),
        ("A", 22, "PROJECT_SPECIFICATION.md", spec),
        ("G", 9, "MVP_ARCHITECTURE.md", architecture),
    ):
        headings = re.findall(r"^#{2,3} (.+)$", content, re.MULTILINE)
        for number in range(1, count + 1):
            identifier = f"{prefix}{number:02}" if prefix != "G" else f"G{number}"
            pattern = (
                rf"^{identifier}\b" if prefix != "F" else rf"(?:^{identifier}\b|\b{identifier}$)"
            )
            if not any(re.search(pattern, heading) for heading in headings):
                errors.append(f"{name}:1: missing requirement heading {identifier}")
    acceptance = re.search(r"^## 12\..*?\n(.*?)(?=^## |\Z)", spec, re.M | re.S)
    for number in range(18, 23):
        if not acceptance or not re.search(rf"^### A{number}\b", acceptance.group(1), re.MULTILINE):
            errors.append(f"PROJECT_SPECIFICATION.md:1: A{number} must be in section 12")
    addendum_name = "docs/baseline/SOFTWARE_EXTENSION_ADDENDUM.md"
    addendum = read(root, addendum_name)
    for required in (
        "S3",
        "§10",
        "§11",
        "A18–A22",
        "AGENTS.md",
        "§7",
        "not present in the original v0.2 tabs",
    ):
        if required not in addendum:
            errors.append(f"{addendum_name}:1: missing attribution statement {required!r}")
    return errors


def attribution_errors(root: Path) -> list[str]:
    name = "docs/baseline/ATTRIBUTION.md"
    attribution = read(root, name)
    errors = []
    if SOURCE_REVISION not in attribution:
        errors.append(f"{name}:1: missing cloud source revision")
    for source in ("PROJECT_SPECIFICATION.md", "MVP_ARCHITECTURE.md"):
        match = re.search(
            rf"^\|\s*`?{re.escape(source)}`?\s*\|\s*`?([a-f0-9]{{64}})`?\s*\|",
            attribution,
            re.MULTILINE,
        )
        path = root / source
        if not path.is_file() or not match:
            errors.append(f"{name}:1: missing source or SHA-256 for {source}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != match.group(1):
            errors.append(f"{name}:1: SHA-256 mismatch for {source}")
    return errors


def state_errors(root: Path) -> list[str]:
    errors = []
    roadmap = read(root, "PLAN.md")
    milestone_map = re.search(r"^## 3\..*?\n(.*?)(?=^## |\Z)", roadmap, re.M | re.S)
    rows = (
        []
        if not milestone_map
        else re.findall(r"^\| (M\d{2}) \|.*?\| ([A-Z_]+) \|$", milestone_map.group(1), re.MULTILINE)
    )
    if {row[0] for row in rows} != {f"M{number:02}" for number in range(14)}:
        errors.append("PLAN.md:1: milestone map must contain M00–M13")
    statuses = {
        "NOT_PLANNED",
        "PLANNED",
        "APPROVED",
        "IN_PROGRESS",
        "VERIFYING",
        "VERIFIED",
        "BLOCKED",
    }
    for milestone, status in rows:
        if status not in statuses:
            errors.append(f"PLAN.md:1: unknown status {status} for {milestone}")
        # PLAN.md's higher-priority workflow permits incomplete work in progress.
        # Only a completion claim requires a completed evidence report.
        if status == "VERIFIED":
            report = read(root, f"docs/milestones/{milestone}-report.md")
            if not re.search(r"^\*\*Gate:\*\* VERIFIED\s*$", report, re.MULTILINE):
                errors.append(f"PLAN.md:1: {milestone} {status} requires a VERIFIED report")
    readme = read(root, "README.md")
    section = re.search(r"^## What exists today\s*\n(.*?)(?=^## |\Z)", readme, re.M | re.S)
    if not section or not section.group(1).strip():
        errors.append("README.md:1: missing What exists today section")
    else:
        allowed = (
            "- Harness:",
            "- Baseline:",
            "- Checks:",
            "- CI:",
            "- Conventions:",
            "- License:",
        )
        for line in section.group(1).splitlines():
            if line.strip() and not line.startswith(allowed):
                errors.append("README.md:1: implemented inventory must list only M00 harness items")
    paths = [root / "README.md", *sorted((root / "docs/baseline").glob("*.md"))]
    for path in paths:
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"pip\s+install\s+c1\b|docker\s+pull\s+\S*c1\b|release\s+v", line, re.I):
                errors.append(f"{path.relative_to(root)}:{number}: unsupported product claim")
    return errors


def check(root: Path) -> list[str]:
    return requirement_errors(root) + attribution_errors(root) + state_errors(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    errors = check(parser.parse_args().root)
    for error in errors:
        print(error)
    if not errors:
        print("Baseline checks passed (local integrity and claims; not cloud equivalence).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
