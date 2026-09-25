"""Reject new secrets in tracked and nonignored untracked files, offline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


def check(root: Path) -> int:
    baseline = root / ".secrets.baseline"
    data = json.loads(baseline.read_text(encoding="utf-8"))
    inspectable = json.loads(json.dumps(data))
    # Merely recording a finding is not approval. Every exception must be audited.
    for filename, findings in data["results"].items():
        for finding in findings:
            if finding.get("is_secret") is not False:
                print(f"{filename}: unaudited or real finding in secret baseline")
                return 1
            if not re.fullmatch(r"[a-f0-9]{40}", finding.get("hashed_secret", "")):
                print(f"{filename}: invalid secret fingerprint in baseline")
                return 1
    for findings in inspectable["results"].values():
        for finding in findings:
            del finding["hashed_secret"]
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
    )
    files = sorted(
        {
            name
            for name in output.decode().split("\0")
            if name and (root / name).is_file() and name != ".secrets.baseline"
        }
    )
    result = 0
    # The hook can update line offsets or trim old findings. Give it a disposable
    # baseline so a read-only check neither edits the source nor requires staging.
    with tempfile.TemporaryDirectory(prefix="c1-secret-check-") as directory:
        # A baseline records audited findings, not permission to disable detectors
        # or add broad exclusions. Compare settings before the hook loads them.
        empty = Path(directory) / "empty.txt"
        empty.touch()
        defaults_run = subprocess.run(
            ["detect-secrets", "scan", "--no-verify", str(empty)],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        defaults = json.loads(defaults_run.stdout)
        if any(
            data.get(key) != defaults[key] for key in ("version", "plugins_used", "filters_used")
        ):
            print("Secret check rejected detector/filter configuration drift from pinned defaults.")
            return 1
        # Scan baseline configuration too. Only validated fingerprints are omitted:
        # scanning their hashes would create recursive false-positive exceptions.
        baseline_content = Path(directory) / "baseline-content.json"
        baseline_content.write_text(json.dumps(inspectable), encoding="utf-8")
        inspected = subprocess.run(
            ["detect-secrets-hook", "--no-verify", "--", str(baseline_content)],
            cwd=root,
            capture_output=True,
        )
        if inspected.returncode:
            print("Secret check rejected baseline contents (fingerprints excluded).")
            return 1
        scratch_baseline = Path(directory) / "baseline.json"
        scratch_baseline.write_text(json.dumps(data), encoding="utf-8")
        for start in range(0, len(files), 100):
            completed = subprocess.run(
                [
                    "detect-secrets-hook",
                    "--no-verify",
                    "--baseline",
                    str(scratch_baseline),
                    "--",
                    *files[start : start + 100],
                ],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if completed.returncode not in (0, 3):
                # Hook diagnostics can include source snippets; never print secret values.
                print(f"Secret check rejected a batch of files (exit {completed.returncode}).")
                print("Inspect locally with detect-secrets; do not copy raw findings to evidence.")
                result = 1
    if not result:
        print(f"Secret check passed for {len(files)} tracked/nonignored files (offline).")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return check(parser.parse_args().root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
