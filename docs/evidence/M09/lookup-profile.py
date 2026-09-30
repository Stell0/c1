"""Profile one software lookup and one test-development package on a fresh load.

Times the phases of the authorized selection (plan, records) separately and
records a cProfile summary. Budget raised to 30,000 ms only for measurement.
"""

from __future__ import annotations

import asyncio
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.software import load  # noqa: E402

BODY = {"target": {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}, "limit": 200}


async def main() -> None:
    result: dict = {}
    async with live_case() as case:
        await load(case)
        runtime = case.runtime
        principal = await case.principal("carol")
        deadline = time.monotonic() + 60
        start = time.monotonic()
        plan, _ = await runtime.query.selection(principal, deadline=deadline)
        result["selection_s"] = round(time.monotonic() - start, 3)
        result["authorized_ids"] = len(plan.authorized_ids)
        head = await runtime.knowledge.head()
        start = time.monotonic()
        records = await runtime.query.records(plan, head, deadline=deadline)
        result["records_s"] = round(time.monotonic() - start, 3)
        result["records"] = len(dict(records.items()))
        await runtime.query.planner.finalize(principal, plan, deadline=deadline)
        profiler = cProfile.Profile()
        profiler.enable()
        start = time.monotonic()
        response = await case.request("POST", "/v1/software/lookup", actor="carol", json=BODY)
        result["lookup_s"] = round(time.monotonic() - start, 3)
        profiler.disable()
        result["lookup_status"] = response.status_code
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(45)
        result["profile"] = stream.getvalue().splitlines()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
