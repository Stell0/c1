"""M08-T02: a target pins snapshots; newer snapshots never change the request."""

from __future__ import annotations

from tests.integration.m08.conftest import (
    Software,
    commit,
    lookup_all,
    resolve,
    revision_after,
    snapshot,
)


def test_t02_target_pinning_and_explicit_branch_resolution(software: Software) -> None:
    case = software.case
    from scripts import software_producer as sp

    async def run() -> None:
        target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
        current = await lookup_all(case, "carol", {"target": target})
        allowed_commits = {commit(software, "a1"), commit(software, "b1")}
        for item in current:
            if item["kind"] == "occurrence":
                assert item["target_member"] in {snapshot("a1"), snapshot("b1")}
                assert item["citation"]["commit"] in allowed_commits
            if item["kind"] == "run":
                assert set(item["target_member"]) <= {snapshot("a1"), snapshot("b1")}
            if item["kind"] == "document":
                assert item["commit"] in allowed_commits
                assert item["target_member"] in {snapshot("a1"), snapshot("b1")}
            if item["kind"] == "relationship" and item["evidence"]["target_member"]:
                assert item["evidence"]["target_member"] in {snapshot("a1"), snapshot("b1")}
        runs = {item["id"] for item in current if item["kind"] == "run"}
        # Fixture v1.1 (M09) adds a mocked b1 run and an a1 run under `py312`.
        assert runs == {
            sp.ident(f"test-run/{key}", "test-run")
            for key in ("live-a1b1", "mocked-b1", "unit-a1-py312")
        }
        operations = {item["operation_id"] for item in current if item["kind"] == "operation"}
        assert operations == {"createInvoice", "getInvoice"}
        documents = {item["path"] for item in current if item["kind"] == "document"}
        assert documents == {"docs/invoicing.md", "CONTRIBUTING.md"}

        # Between these two C1 revisions only a2/b2 content was ingested (their
        # snapshots, sources, files, contracts, and docs). A request pinned to
        # a1/b1 must return exactly the same items at both revisions.
        before = await lookup_all(
            case, "carol", {"target": target, "revision": revision_after(software, "scip/b1")}
        )
        after = await lookup_all(
            case, "carol", {"target": target, "revision": revision_after(software, "scip/b2")}
        )
        assert before == after
        assert before

        ledger = sp.repository_id("ledger")
        early = await resolve(
            case,
            "carol",
            {
                "branches": [{"repository": ledger, "branch": "main"}],
                "as_of": "2026-01-20T00:00:00Z",
            },
        )
        assert [item["id"] for item in early["target"]["snapshots"]] == [snapshot("a1")]
        assert early["branch_resolutions"][0]["snapshot"] == snapshot("a1")
        assert early["branch_resolutions"][0]["observed_at"] == "2026-01-15T00:00:00Z"
        late = await resolve(
            case,
            "carol",
            {
                "branches": [{"repository": ledger, "branch": "main"}],
                "as_of": "2026-02-20T00:00:00Z",
            },
        )
        assert [item["id"] for item in late["target"]["snapshots"]] == [snapshot("a2")]
        none = await resolve(
            case,
            "carol",
            {
                "snapshots": [snapshot("b1")],
                "branches": [{"repository": ledger, "branch": "main"}],
                "as_of": "2026-01-01T00:00:00Z",
            },
        )
        assert none["unresolved"] == [
            {"repository": ledger, "branch": "main", "reason": "no-observation"}
        ]
        assert [item["id"] for item in none["target"]["snapshots"]] == [snapshot("b1")]

        missing = await resolve(case, "carol", {"contracts": []}, status=400)
        assert missing["code"] == "C1-SW-002"
        no_instant = await resolve(
            case, "carol", {"branches": [{"repository": ledger, "branch": "main"}]}, status=400
        )
        assert no_instant["code"] == "C1-SW-003"
        two = await resolve(
            case, "carol", {"snapshots": [snapshot("a1"), snapshot("a2")]}, status=400
        )
        assert two["code"] == "C1-SW-004"

    software.run(run())
