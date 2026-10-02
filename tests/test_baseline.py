"""Fidelity and negative checks for the attributed local source baseline."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from scripts.check_baseline import (
    attribution_errors,
    check,
    requirement_errors,
    state_errors,
)

ROOT = Path(__file__).resolve().parents[1]


def _copy_baseline_tree(destination: Path) -> Path:
    """Copy just the documents read by baseline checks into an isolated fixture."""
    for name in (
        "PLAN.md",
        "README.md",
        "PROJECT_SPECIFICATION.md",
        "MVP_ARCHITECTURE.md",
    ):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copytree(ROOT / "docs" / "baseline", destination / "docs" / "baseline")
    shutil.copytree(ROOT / "docs" / "milestones", destination / "docs" / "milestones")
    return destination


def test_requirement_ids_present() -> None:
    assert requirement_errors(ROOT) == []


def test_attribution_hashes_match() -> None:
    assert attribution_errors(ROOT) == []


def test_baseline_check_has_no_diagnostics() -> None:
    assert check(ROOT) == []


def test_removing_requirement_heading_fails_even_if_id_is_mentioned_elsewhere(
    tmp_path: Path,
) -> None:
    fixture = _copy_baseline_tree(tmp_path)
    specification = fixture / "PROJECT_SPECIFICATION.md"
    original = specification.read_text(encoding="utf-8")
    heading = "### A18 — Coding-agent test context"
    assert original.count(heading) == 1
    specification.write_text(
        original.replace(
            heading, "A18 is still mentioned here, but its source heading is missing.", 1
        ),
        encoding="utf-8",
    )

    errors = requirement_errors(fixture)
    assert errors
    assert any("A18" in error and "PROJECT_SPECIFICATION.md" in error for error in errors)


def test_source_mutation_invalidates_recorded_hash(tmp_path: Path) -> None:
    fixture = _copy_baseline_tree(tmp_path)
    specification = fixture / "PROJECT_SPECIFICATION.md"
    specification.write_text(
        specification.read_text(encoding="utf-8") + "\nSynthetic mutation.\n",
        encoding="utf-8",
    )

    errors = attribution_errors(fixture)
    assert errors
    assert any("PROJECT_SPECIFICATION.md" in error for error in errors)


def test_verified_roadmap_state_requires_a_verified_report(tmp_path: Path) -> None:
    fixture = _copy_baseline_tree(tmp_path)
    plan = fixture / "PLAN.md"
    contents = plan.read_text(encoding="utf-8")
    contents, changed = re.subn(
        r"(^\| M00 \|.*\| )[A-Z_]+( \|$)", r"\g<1>VERIFIED\2", contents, flags=re.M
    )
    assert changed == 1
    (fixture / "docs/milestones/M00-report.md").unlink(missing_ok=True)
    plan.write_text(contents, encoding="utf-8")

    errors = state_errors(fixture)
    assert errors
    assert any("M00" in error and "PLAN.md" in error for error in errors)


@pytest.mark.parametrize("status", ["IN_PROGRESS", "VERIFYING"])
def test_active_roadmap_status_does_not_require_a_report(
    tmp_path: Path,
    status: str,
) -> None:
    fixture = _copy_baseline_tree(tmp_path)
    plan = fixture / "PLAN.md"
    contents = plan.read_text(encoding="utf-8")
    contents, changed = re.subn(
        r"(^\| M00 \|.*\| )[A-Z_]+( \|$)",
        rf"\g<1>{status}\2",
        contents,
        flags=re.M,
    )
    assert changed == 1
    (fixture / "docs/milestones/M00-report.md").unlink(missing_ok=True)
    plan.write_text(contents, encoding="utf-8")

    assert not any("M00" in error for error in state_errors(fixture))


@pytest.mark.parametrize("label", ["- **Explorer:** planned UI.", "- Explorer: planned UI."])
def test_unlisted_capability_in_readme_inventory_fails(tmp_path: Path, label: str) -> None:
    fixture = _copy_baseline_tree(tmp_path)
    readme = fixture / "README.md"
    original = readme.read_text(encoding="utf-8")
    heading = "## What exists today\n\n"
    assert heading in original
    readme.write_text(original.replace(heading, heading + label + "\n", 1), encoding="utf-8")
    assert (
        "README.md:1: implemented inventory contains an unrecognized capability heading"
        in check(fixture)
    )
