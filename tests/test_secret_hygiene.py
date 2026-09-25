"""Verify secret scanning catches new content without touching the real checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET_CHECKER = ROOT / "scripts" / "check_secrets.py"


def _temporary_git_repository(path: Path) -> None:
    shutil.copy2(ROOT / ".secrets.baseline", path / ".secrets.baseline")
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)


@pytest.mark.parametrize("track_file", [False, True], ids=["untracked", "tracked"])
def test_repository_secret_check_rejects_synthetic_aws_key_and_accepts_clean_file(
    tmp_path: Path,
    track_file: bool,
) -> None:
    _temporary_git_repository(tmp_path)
    fixture = tmp_path / "synthetic-fixture.txt"
    synthetic_key = "AKIA" + "A1B2C3D4E5F6G7H8"
    fixture.write_text(f"AWS access key: {synthetic_key}\n", encoding="utf-8")
    if track_file:
        subprocess.run(["git", "-C", str(tmp_path), "add", fixture.name], check=True)

    environment = os.environ.copy()
    environment.pop("DETECT_SECRETS_BASELINE", None)
    result_with_key = subprocess.run(
        [sys.executable, str(SECRET_CHECKER), "--root", str(tmp_path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_with_key.returncode != 0, result_with_key.stdout + result_with_key.stderr

    fixture.write_text("Synthetic public fixture with no credential.\n", encoding="utf-8")
    result_clean = subprocess.run(
        [sys.executable, str(SECRET_CHECKER), "--root", str(tmp_path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_clean.returncode == 0, result_clean.stdout + result_clean.stderr


def test_repository_secret_check_rejects_unaudited_baseline_finding_in_empty_repo(
    tmp_path: Path,
) -> None:
    _temporary_git_repository(tmp_path)
    baseline_path = tmp_path / ".secrets.baseline"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["results"]["synthetic-fixture.txt"] = [
        {
            "type": "AWS Access Key",
            "hashed_secret": "a" * 40,
            "is_secret": None,
            "line_number": 1,
        }
    ]
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SECRET_CHECKER), "--root", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unaudited" in result.stdout.lower()


def test_repository_secret_check_scans_extra_baseline_fields(tmp_path: Path) -> None:
    _temporary_git_repository(tmp_path)
    baseline_path = tmp_path / ".secrets.baseline"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["synthetic_fixture_note"] = "AWS access key: " + "AKIA" + "A1B2C3D4E5F6G7H8"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SECRET_CHECKER), "--root", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "baseline contents" in result.stdout.lower()


@pytest.mark.parametrize(
    "configuration_case",
    ["missing_detector", "changed_detector_limit", "extra_excluding_filter"],
)
def test_repository_secret_check_rejects_detector_or_filter_configuration_changes(
    tmp_path: Path,
    configuration_case: str,
) -> None:
    _temporary_git_repository(tmp_path)
    baseline_path = tmp_path / ".secrets.baseline"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    if configuration_case == "missing_detector":
        baseline["plugins_used"] = [
            plugin for plugin in baseline["plugins_used"] if plugin["name"] != "KeywordDetector"
        ]
    elif configuration_case == "changed_detector_limit":
        high_entropy = next(
            plugin
            for plugin in baseline["plugins_used"]
            if plugin["name"] == "Base64HighEntropyString"
        )
        high_entropy["limit"] = 4.6
    else:
        baseline["filters_used"].append(
            {
                "path": "detect_secrets.filters.regex.should_exclude_file",
                "pattern": ".*",
            }
        )
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SECRET_CHECKER), "--root", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "detector/filter configuration" in result.stdout.lower()


def test_detect_secrets_scan_finds_synthetic_key_without_network_verification(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "synthetic-fixture.txt"
    synthetic_key = "AKIA" + "A1B2C3D4E5F6G7H8"
    fixture.write_text(f"AWS access key: {synthetic_key}\n", encoding="utf-8")

    result = subprocess.run(
        ["detect-secrets", "scan", "--no-verify", str(fixture)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    snapshot = json.loads(result.stdout)
    findings = [
        finding for file_findings in snapshot["results"].values() for finding in file_findings
    ]
    assert any(finding["type"] == "AWS Access Key" for finding in findings)
