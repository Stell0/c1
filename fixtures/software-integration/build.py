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
        "version": "1.3.0",
        "profile": "software",
        "scopes": {
            "sw-shared": "Software shared",
            "sw-ledger": "Ledger source",
            "sw-shop": "Shop source",
            "sw-restricted": "Restricted pricing source",
            # v1.3 (M11 D7, D8): a quarantined drafting scope, the widened
            # documentation audience, and publication receipts.
            "drafts-bob": "Bob's documentation drafts",
            "sw-docs": "Published software documentation",
            "sw-publications": "Publication receipts",
        },
        # Human readers per scope; carol also reviews. Dave cannot read restricted code.
        "readers": {
            "carol": ["sw-shared", "sw-ledger", "sw-shop", "sw-restricted"],
            "dave": [
                "sw-shared",
                "sw-ledger",
                "sw-shop",
                "drafts-bob",
                "sw-docs",
                "sw-publications",
            ],
            "alice": ["sw-shared", "sw-docs", "sw-publications"],
            "bob": [
                "sw-shared",
                "sw-ledger",
                "sw-shop",
                "drafts-bob",
                "sw-docs",
                "sw-publications",
            ],
        },
        # Who creates each scope (and so administers it), its kind, and which
        # producers hold roles there; unlisted scopes use the defaults.
        "scope_settings": {
            "drafts-bob": {"kind": "drafting", "creator": "admin", "producers": []},
            # The publisher reads widened documentation, never the drafting scope.
            "sw-docs": {"creator": "frank", "producers": [], "service_readers": ["ci"]},
            "sw-publications": {"producers": ["ci"]},
        },
        # Extra scope roles, granted by the scope's creator (M11 §1a item 6).
        "scope_roles": {
            "drafts-bob": [
                ["bob", "contributor"],
                ["bob", "creator"],
                ["dave", "reviewer"],
                ["carol", "access_admin"],
            ],
            "sw-docs": [["carol", "access_admin"]],
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
        "configurations": {
            "default": ["python=3.13", "ledger_url=http://ledger.test"],
            "py312": ["python=3.12", "ledger_url=http://ledger.test"],
        },
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
            # v1.1 (M09): a mocked shop run at b1, and a ledger run at a1 under
            # another configuration (never verification of a `default` target).
            {
                "key": "mocked-b1",
                "test_case": "shop-mocked",
                "snapshots": ["b1"],
                "configuration": "default",
                "mode": "mocked",
                "mocked": ["ledger"],
                "report": "runs/mocked-b1.xml",
                "exercised": [],
                "started_at": "2026-01-21T09:00:00Z",
                "ended_at": "2026-01-21T09:00:01Z",
            },
            {
                "key": "unit-a1-py312",
                "test_case": "ledger-create",
                "snapshots": ["a1"],
                "configuration": "py312",
                "mode": "live",
                "mocked": [],
                "report": "runs/unit-a1-py312.xml",
                "exercised": [],
                "started_at": "2026-01-22T09:00:00Z",
                "ended_at": "2026-01-22T09:00:01Z",
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
        # v1.1 (M09 D3, D9): declared test-development context. Instructions are
        # stored text only; nothing here is ever executed by C1 or the producer.
        "execution_instructions": {
            "CONTRIBUTING.md": {"repository": "ledger", "heading": "Running tests"},
        },
        "test_fixtures": [
            {
                "repository": "ledger",
                "path": "tests/conftest.py",
                "descriptor": "`tests.conftest`/sample_invoice().",
                "test_case": "ledger-create",
            }
        ],
        # v1.2 (M10 D2, D3, D10): declared support aspects, published support
        # guides in sw-shared, and attributed aspect claims on code.
        "aspects": {
            "configuration": "Configuration",
            "retry": "Retry",
            "timeout": "Timeout",
            "invoice-creation": "Invoice creation procedure",
        },
        "guides": {
            "guides/ledger-ops-1.0.md": {
                "issued": "2026-01-05",
                "describes": ["a1", "b1"],
                "documents": {"capability": "invoice-creation", "operations": ["createInvoice"]},
                "sections": {
                    "Configuration": ["configuration"],
                    "Creating an invoice": ["invoice-creation"],
                },
                "not_applicable_to": {},
            },
            "guides/ledger-ops-1.1.md": {
                "issued": "2026-02-05",
                "describes": ["a2", "b2"],
                "documents": {"capability": "invoice-creation", "operations": ["createInvoice"]},
                "sections": {
                    "Configuration": ["configuration"],
                    "Creating an invoice": ["invoice-creation"],
                },
                "not_applicable_to": {},
            },
            "guides/shop-troubleshooting.md": {
                "issued": "2026-02-20",
                "describes": [],
                "documents": {"operations": ["createInvoice"]},
                "sections": {"Invoice creation fails": ["invoice-creation"]},
                # The declared section is the evidence for the negative declaration.
                "not_applicable_to": {"b2": "Applicability"},
            },
        },
        "code_aspects": [
            {
                "repository": "ledger",
                "snapshot": "a2",
                "descriptor": "`ledger.api`/create_invoice().",
                "aspect": "retry",
            },
            {
                "repository": "shop",
                "snapshot": "b2",
                "descriptor": "`shop.ledger_client`/post_invoice().",
                "aspect": "retry",
            },
        ],
        # v1.3 (M11 D9): part-level `documents` per section of the invoicing guide.
        "part_documents": {
            "docs/invoicing.md": {
                "Creating an invoice": ["createInvoice"],
                "Reading an invoice": ["getInvoice"],
            }
        },
        # The external review-candidate rule (scripts/doc_review_rule.py) runs
        # once over this target during the load.
        "review_rule": {
            "rule": "doc-dependency-change/1",
            "target": {"snapshots": ["a2", "b2"], "contract": "a2"},
            "checked_at": "2026-03-01T09:00:00Z",
        },
        # Bob's draft and the publisher report; tests and the demo submit them.
        "draft": {
            "title": "Invoicing (1.1)",
            "revises": {"snapshot": "a1", "path": "docs/invoicing.md"},
            "target": {"snapshots": ["a2", "b2"], "contract": "a2"},
            "parts": [
                {
                    "text": "## Creating an invoice",
                    "kind": "heading-2",
                    "lineage": [],
                },
                {
                    "text": "Call `POST /invoices` with a `customer_id`, an amount, "
                    "and optionally `retries`.",
                    "kind": "text",
                    "lineage": [
                        {"contract": "a2"},
                        {
                            "repository": "ledger",
                            "snapshot": "a2",
                            "descriptor": "`ledger.api`/create_invoice().",
                        },
                        {
                            "repository": "shop",
                            "snapshot": "b2",
                            "descriptor": "`shop.client`/submit_order().",
                        },
                    ],
                },
            ],
            "publication": {
                "locator": "https://git.example.invalid/ledger/docs/invoicing.md",
                "published_at": "2026-03-05T12:00:00Z",
            },
        },
        # A checked-in review note: a1 `validate` accepts zero, which the
        # documentation says is rejected. a2 fixes it.
        "discrepancies": [
            {
                "key": "a1-zero-amount",
                "snapshot": "a1",
                "implementation": {"path": "ledger/api.py", "quote": "return amount >= 0"},
                "normative": {
                    "path": "docs/invoicing.md",
                    "quote": "The amount must be greater than zero; zero is rejected with 422.",
                },
            },
            {
                "key": "a1-zero-amount-guide",
                "snapshot": "a1",
                "implementation": {"path": "ledger/api.py", "quote": "return amount >= 0"},
                "normative": {
                    "path": "guides/ledger-ops-1.0.md",
                    "quote": "Zero amounts are rejected.",
                },
            },
        ],
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        commits = build_repositories(Path(directory))
    (HERE / "fixture.json").write_text(json.dumps(build_fixture(commits), indent=2) + "\n")


if __name__ == "__main__":
    main()
