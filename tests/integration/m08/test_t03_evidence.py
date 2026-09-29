"""M08-T03: every citation resolves to its pinned commit, path, range, and digest."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m08.conftest import Software, lookup_all, resolve, snapshot

ROOT = Path(__file__).resolve().parents[3]
C1 = "urn:c1:ns:core#"


def _build_repositories(target: Path) -> dict[str, dict[str, str]]:
    spec = importlib.util.spec_from_file_location(
        "software_fixture_build", ROOT / "fixtures/software-integration/build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result: dict[str, dict[str, str]] = module.build_repositories(target)
    return result


def _show(repository: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=repository, check=True, capture_output=True
    ).stdout


def test_t03_citations_resolve_to_immutable_snapshot_content(software: Software) -> None:
    case = software.case

    async def run() -> None:
        target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
        occurrences = await lookup_all(case, "carol", {"target": target, "kinds": ["occurrences"]})
        assert occurrences
        with tempfile.TemporaryDirectory() as directory:
            commits = _build_repositories(Path(directory))
            assert {key: value["commit"] for key, value in commits.items()} == {
                key: value["commit"] for key, value in software.fixture["snapshots"].items()
            }
            for item in occurrences:
                citation = item["citation"]
                repository = "ledger" if item["target_member"] == snapshot("a1") else "shop"
                data = _show(Path(directory) / repository, citation["commit"], citation["path"])
                assert citation["content_digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
                lines = data.decode("utf-8").splitlines(keepends=True)
                span = item["range"]
                token = lines[span["start_line"]][span["start_character"] : span["end_character"]]
                name = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", item["symbol"]["descriptors"])[-1]
                assert token == name
                if citation.get("excerpt"):
                    assert citation["excerpt"] in data.decode("utf-8")
                    expected = (
                        "complete-unit"
                        if citation["part_kind"].startswith("code-unit")
                        else "excerpt"
                    )
                    assert citation["code_completeness"] == expected
                document = await case.request(
                    "GET",
                    "/v1/resources/" + quote(citation["document_id"], safe=""),
                    actor="carol",
                )
                assert document.status_code == 200, document.text
                assert (
                    document.json()["properties"][C1 + "sourceRevision"][0]["lexical"]
                    == citation["commit"]
                )

        # The branch label later moved to a2; a1 citations are unchanged, and the
        # label only matters when a caller explicitly resolves it at an instant.
        moved = await resolve(
            case,
            "carol",
            {
                "branches": [{"repository": sp.repository_id("ledger"), "branch": "main"}],
                "as_of": "2026-03-01T00:00:00Z",
            },
        )
        assert [item["id"] for item in moved["target"]["snapshots"]] == [snapshot("a2")]
        again = await lookup_all(case, "carol", {"target": target, "kinds": ["occurrences"]})
        assert again == occurrences

    software.run(run())
