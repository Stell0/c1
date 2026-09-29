"""M08-T04: partial ingestion stays explicit; nothing is asserted absent or relabeled."""

from __future__ import annotations

from scripts import software_producer as sp
from tests.integration.m08.conftest import CaseLoader, Software, lookup_all, snapshot


def test_t04_partial_import_is_explicit_and_never_relabeled(software: Software) -> None:
    case = software.case

    async def run() -> None:
        b2 = {"snapshots": [snapshot("b2")]}
        items = await lookup_all(
            case, "carol", {"target": b2, "kinds": ["coverage", "issues", "unresolved"]}
        )
        coverage = {
            (item["method"], tuple(item["analyzed"])): item["state"]
            for item in items
            if item["kind"] == "coverage"
        }
        scip = {key: value for key, value in coverage.items() if key[0] == "scip-occurrences"}
        assert ("scip-occurrences", ("shop/pricing_internal.py",)) in scip
        assert scip[("scip-occurrences", ("shop/pricing_internal.py",))] == "complete"
        shop = [value for key, value in scip.items() if "shop/broken.py" in key[1]]
        assert shop == ["partial"]
        issues = [item for item in items if item["kind"] == "issue"]
        assert [(item["code"], item["path"]) for item in issues] == [
            ("C1-SW-PARSE-001", "shop/broken.py")
        ]
        unresolved = [item for item in items if item["kind"] == "unresolved"]
        assert unresolved and {item["reason"] for item in unresolved} == {"not-indexed"}
        assert {item["symbol_text"] for item in unresolved} == {"shop.broken.refund"}

        occurrences = await lookup_all(case, "carol", {"target": b2, "kinds": ["occurrences"]})
        # The failed file's index entries were not used, so nothing defines refund;
        # its callers are unresolved rather than asserted to have no dependency.
        assert not [
            item for item in occurrences if "refund" in (item["symbol"]["descriptors"] or "")
        ]
        assert {item["citation"]["path"] for item in occurrences}.isdisjoint({"shop/broken.py"})

        # b1 extraction stays attributed to b1; none of it is relabeled as b2.
        b1 = await lookup_all(
            case, "carol", {"target": {"snapshots": [snapshot("b1")]}, "kinds": ["occurrences"]}
        )
        assert {item["id"] for item in b1}.isdisjoint({item["id"] for item in occurrences})
        assert {item["target_member"] for item in b1} == {snapshot("b1")}

        # A producer that stops before its coverage record leaves coverage unknown:
        # its records exist, but no coverage record states completion.
        planner = software.loaded["planner"]
        unfinished = planner.ci_run(
            {
                **software.fixture["test_runs"][0],
                "key": "unfinished-a1b1",
                "started_at": "2026-03-01T09:00:00Z",
                "ended_at": "2026-03-01T09:00:01Z",
            }
        )
        loader = CaseLoader(case)
        await loader.apply_changeset(
            sp.operations(unfinished.records),
            author="ci",
            reviewer="reviewer",
            base=await case.knowledge.head(),
        )
        after = await lookup_all(
            case,
            "carol",
            {
                "target": {"snapshots": [snapshot("a1"), snapshot("b1")]},
                "kinds": ["coverage", "runs"],
            },
        )
        assert sp.ident("test-run/unfinished-a1b1", "test-run") in {
            item["id"] for item in after if item["kind"] == "run"
        }
        assert unfinished.activity["id"] not in {
            item["activity"] for item in after if item["kind"] == "coverage"
        }

    software.run(run())
