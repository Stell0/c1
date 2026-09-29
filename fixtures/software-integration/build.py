"""Deterministic `software-integration` fixture construction (M08 D13).

Two tiny synthetic Python repositories, ledger (a1, a2) and shop (b1, b2), are
committed into fresh git repositories with fixed identities and dates, so the
commit IDs are reproducible and asserted. `fixture.json` records those IDs and
every declared, independently specified fact the producers need. No network,
credentials, or private data are involved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

REPOSITORIES: dict[str, dict[str, Any]] = {
    "ledger": {
        "product": "ledger",
        "scope": "sw-ledger",
        "package": "ledger",
        "snapshots": [
            {"key": "a1", "release": "1.0.0", "committed_at": "2026-01-10T10:00:00+00:00"},
            {"key": "a2", "release": "1.1.0", "committed_at": "2026-02-10T10:00:00+00:00"},
        ],
    },
    "shop": {
        "product": "shop",
        "scope": "sw-shop",
        "package": "shop",
        "snapshots": [
            {"key": "b1", "release": "2.0.0", "committed_at": "2026-01-12T10:00:00+00:00"},
            {"key": "b2", "release": "2.1.0", "committed_at": "2026-02-12T10:00:00+00:00"},
        ],
    },
}

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "C1 Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "C1 Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(repo),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
        **GIT_IDENTITY,
        **(env or {}),
    }
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.fileMode=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=repo,
        env=base,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_repositories(target: Path) -> dict[str, dict[str, str]]:
    """Create both git repositories under `target`; return commit and tree IDs."""
    result: dict[str, dict[str, str]] = {}
    for name, spec in REPOSITORIES.items():
        repo = target / name
        repo.mkdir(parents=True)
        _git(repo, "init", "-q")
        for snapshot in spec["snapshots"]:
            for item in repo.iterdir():
                if item.name != ".git":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
            source = HERE / "repos" / name / snapshot["key"]
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    destination = repo / path.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(path.read_bytes())
            _git(repo, "add", "-A")
            stamp = snapshot["committed_at"]
            _git(
                repo,
                "commit",
                "-q",
                "-m",
                f"{name} {snapshot['key']}",
                env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
            )
            result[snapshot["key"]] = {
                "commit": _git(repo, "rev-parse", "HEAD"),
                "tree": _git(repo, "rev-parse", "HEAD^{tree}"),
            }
    return result


def build_fixture(commits: dict[str, dict[str, str]]) -> dict[str, Any]:
    snapshots = {
        snapshot["key"]: {
            "repository": name,
            "release": snapshot["release"],
            "committed_at": snapshot["committed_at"],
            **commits[snapshot["key"]],
        }
        for name, spec in REPOSITORIES.items()
        for snapshot in spec["snapshots"]
    }
    return {
        "name": "software-integration",
        "version": "1.0.0",
        "profile": "software",
        "scopes": {
            "sw-shared": "Software shared",
            "sw-ledger": "Ledger source",
            "sw-shop": "Shop source",
            "sw-restricted": "Restricted pricing source",
        },
        # Human readers per scope; carol also reviews. Dave cannot read restricted code.
        "readers": {
            "carol": ["sw-shared", "sw-ledger", "sw-shop", "sw-restricted"],
            "dave": ["sw-shared", "sw-ledger", "sw-shop"],
            "alice": ["sw-shared"],
        },
        "products": {
            "ledger": {"label": "Ledger", "scope": "sw-shared"},
            "shop": {"label": "Shop", "scope": "sw-shared"},
        },
        "repositories": {
            name: {
                "product": spec["product"],
                "scope": spec["scope"],
                "package": spec["package"],
                "snapshots": [item["key"] for item in spec["snapshots"]],
            }
            for name, spec in REPOSITORIES.items()
        },
        "snapshots": snapshots,
        # A mutable label observed at two moments; never evidence (M08 D2).
        "branch_observations": [
            {
                "repository": "ledger",
                "branch": "main",
                "snapshot": "a1",
                "observed_at": "2026-01-15T00:00:00Z",
            },
            {
                "repository": "ledger",
                "branch": "main",
                "snapshot": "a2",
                "observed_at": "2026-02-15T00:00:00Z",
            },
            {
                "repository": "shop",
                "branch": "main",
                "snapshot": "b1",
                "observed_at": "2026-01-16T00:00:00Z",
            },
            {
                "repository": "shop",
                "branch": "main",
                "snapshot": "b2",
                "observed_at": "2026-02-16T00:00:00Z",
            },
        ],
        "path_scopes": {"shop/pricing_internal.py": "sw-restricted"},
        "capability": {
            "key": "invoice-creation",
            "label": "Invoice creation",
            "scope": "sw-shared",
            # Attributed interpretation (not static extraction) by the analyzer.
            "implemented_by": [
                ["ledger", "`ledger.api`/create_invoice()."],
                ["shop", "`shop.client`/submit_order()."],
            ],
        },
        "contracts": {"repository": "ledger", "path": "openapi.json", "provider": "ledger"},
        "documentation": {
            "docs/invoicing.md": {
                "repository": "ledger",
                "describes": ["a1", "b1"],
                "documents": {"capability": "invoice-creation", "operations": ["createInvoice"]},
            },
            "CONTRIBUTING.md": {"repository": "ledger", "describes": ["a1", "a2"], "documents": {}},
        },
        "configurations": {"default": ["python=3.13", "ledger_url=http://ledger.test"]},
        "test_cases": {
            "ledger-create": {
                "repository": "ledger",
                "descriptor": "`tests.test_api`/test_create_invoice_stores_invoice().",
                "verifies": {"operations": ["createInvoice"]},
            },
            "shop-mocked": {
                "repository": "shop",
                "descriptor": "`tests.test_client`/test_submit_order_with_mocked_ledger().",
                "verifies": {"capability": "invoice-creation"},
            },
            "shop-live": {
                "repository": "shop",
                "descriptor": "`tests.test_integration`/test_submit_order_against_live_ledger().",
                "verifies": {"capability": "invoice-creation", "operations": ["createInvoice"]},
            },
        },
        "test_runs": [
            {
                "key": "live-a1b1",
                "test_case": "shop-live",
                "snapshots": ["a1", "b1"],
                "configuration": "default",
                "mode": "live",
                "mocked": [],
                "report": "runs/live-a1b1.xml",
                "exercised": ["createInvoice"],
                "started_at": "2026-01-20T09:00:00Z",
                "ended_at": "2026-01-20T09:00:01Z",
            },
            {
                "key": "mocked-b2",
                "test_case": "shop-mocked",
                "snapshots": ["b2"],
                "configuration": "default",
                "mode": "mocked",
                "mocked": ["ledger"],
                "report": "runs/mocked-b2.xml",
                "exercised": [],
                "started_at": "2026-02-20T09:00:00Z",
                "ended_at": "2026-02-20T09:00:01Z",
            },
            {
                "key": "unit-a2",
                "test_case": "ledger-create",
                "snapshots": ["a2"],
                "configuration": "default",
                "mode": "live",
                "mocked": [],
                "report": "runs/unit-a2.xml",
                "exercised": [],
                "started_at": "2026-02-21T09:00:00Z",
                "ended_at": "2026-02-21T09:00:01Z",
            },
        ],
        # The competing analyzer resolves one call by name only and disagrees
        # with the indexer's reference-based static call (M08 D11, T05).
        "name_match_calls": ["validate"],
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        commits = build_repositories(Path(directory))
    (HERE / "fixture.json").write_text(json.dumps(build_fixture(commits), indent=2) + "\n")


if __name__ == "__main__":
    main()
