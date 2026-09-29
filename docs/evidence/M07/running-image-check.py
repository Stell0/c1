"""Read-only check of running c1-dev service images against images.json.

Run from the repository root with:
    PYTHONPATH=. uv run --locked python docs/evidence/M07/running-image-check.py

Uses probes.config.runtime(), which selects the supported podman/docker CLI
(default podman), and the same c1-dev Compose project/service labels as
scripts/stack.py. It never prints container environment or full inspect data.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from probes.config import runtime

ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "pyproject.toml").is_file():
    raise SystemExit("running-image-check.py must remain under the C1 repository")
MANIFEST = ROOT / "deployment/images.json"
SERVICES = ("terminusdb", "postgres", "openfga", "keycloak")


def call(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def normalize_sha256(value: str) -> str | None:
    """Normalize a SHA-256 digest with or without its runtime prefix."""
    encoded = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", encoded) is None:
        return None
    return f"sha256:{encoded}"


def main() -> None:
    cli = runtime()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if set(manifest) != set(SERVICES):
        raise SystemExit("deployment/images.json service set differs from expected c1-dev services")

    for service in SERVICES:
        ids = call(
            cli,
            "ps",  # Running containers only.
            "--filter",
            "label=com.docker.compose.project=c1-dev",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ).splitlines()
        if len(ids) != 1:
            raise SystemExit(f"{service}: expected one running c1-dev container; found {len(ids)}")

        container_id = ids[0]
        container_image_id = call(cli, "inspect", "--format", "{{.Image}}", container_id)
        inspected = call(
            cli,
            "image",
            "inspect",
            "--format",
            "{{.Id}}\t{{json .RepoDigests}}",
            container_image_id,
        ).split("\t", 1)
        if len(inspected) != 2:
            raise SystemExit(f"{service}: unexpected image inspect fields")
        actual_config_raw, repo_json = inspected
        repo_digests = set(json.loads(repo_json) or [])

        expected = manifest[service]
        actual_config = normalize_sha256(actual_config_raw)
        expected_config = normalize_sha256(expected["config_digest"])
        allowed_repos = {
            f"{expected['image']}@{expected['digest']}",
            f"{expected['image']}@{expected['platform_digest']}",
        }
        matched_repos = sorted(repo_digests & allowed_repos)
        # A runtime may report either the recorded parent/index digest or
        # platform digest for the running image. Require an exact match to at
        # least one recorded repository reference, plus the exact config ID.
        if (
            actual_config is None
            or expected_config is None
            or actual_config != expected_config
            or not matched_repos
        ):
            raise SystemExit(f"{service}: running image ID/repository digest mismatch")

        # These fields are metadata only; no environment/config is printed.
        print(
            f"{service}: container={container_id} image_id={actual_config} "
            f"repo_digests={','.join(matched_repos)}"
        )


if __name__ == "__main__":
    main()
