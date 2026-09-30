"""M09-T05: a deterministic consumer reproduces the predetermined fail/pass outcome."""

from __future__ import annotations

import asyncio

from scripts import demo_m09_consumer as consumer
from scripts import software_producer as sp
from tests.integration.m03.conftest import live_case
from tests.integration.m09.conftest import ledger_symbol, package, target, units
from tests.integration.software import CaseLoader, load


def test_t05_consumer_reproducibility() -> None:
    """Uses its own fresh repository: it imports new TestRuns."""

    async def run() -> None:
        async with live_case() as case:
            await load(case)
            outcome = await consumer.consume(CaseLoader(case))
            assert outcome["results"] == {"a1": "fail", "a2": "pass"}
            assert outcome["cited"]
            assert [item["state"] for item in outcome["imported"]] == ["applied"] * 3

            # The imported runs appear with target-relative labels in a new request.
            case_id = sp.test_case_id(sp.CONSUMER_CASE)
            before_fix = await package(case, "carol", ledger_symbol(), target("a1", "b1"))
            test = next(
                unit for unit in units(before_fix, "tests") if unit["test_case"]["id"] == case_id
            )
            assert test["status"] == "matching-run" and test["matching_results"] == ["fail"]
            assert test["definition"] is None  # the reviewed test lives outside the snapshots
            runs = {
                unit["run_id"]: unit
                for unit in units(before_fix, "runs")
                if unit["test_case"] == case_id
            }
            assert runs[sp.ident("test-run/consumer/a1", "test-run")]["match"] == "matching"
            assert runs[sp.ident("test-run/consumer/a2", "test-run")]["match"] == "other-target"
            after_fix = await package(case, "carol", ledger_symbol(), target("a2", "b2"))
            test = next(
                unit for unit in units(after_fix, "tests") if unit["test_case"]["id"] == case_id
            )
            assert test["status"] == "matching-run" and test["matching_results"] == ["pass"]

            # Re-running the consumer is idempotent: identical imports are skipped.
            again = await consumer.consume(CaseLoader(case))
            assert [item["state"] for item in again["imported"]] == ["skipped"] * 3

    asyncio.run(run())
