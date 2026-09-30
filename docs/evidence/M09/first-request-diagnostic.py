"""Diagnose the first software request after a fresh software-integration load.

Two fresh repositories are loaded. In the first, the first and second lookups
are timed as loaded. In the second, the knowledge branch is optimized (layers
rolled up; data unchanged) before the first lookup. The request budget is
raised to 30,000 ms (M07 D22 maximum) only so durations can be measured.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.software import load  # noqa: E402

BODY = {"target": {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}, "limit": 200}


async def timed(case, label: str) -> dict:
    start = time.monotonic()
    response = await case.request("POST", "/v1/software/lookup", actor="carol", json=BODY)
    return {
        "step": label,
        "status": response.status_code,
        "seconds": round(time.monotonic() - start, 3),
    }


async def main() -> None:
    results = []
    for optimize in (False, True):
        async with live_case() as case:
            await load(case)
            log = await case.knowledge._request(
                "GET", f"/api/log/{case.knowledge._database_path}", params={"count": 1000}
            )
            results.append({"optimize": optimize, "commits": len(log.json())})
            if optimize:
                start = time.monotonic()
                response = await case.knowledge._request(
                    "POST", f"/api/optimize/{case.knowledge._database_path}/local/branch/main"
                )
                results.append(
                    {
                        "step": "optimize",
                        "status": response.status_code,
                        "seconds": round(time.monotonic() - start, 3),
                    }
                )
            results.append(await timed(case, "first lookup"))
            results.append(await timed(case, "second lookup"))
    print(
        json.dumps(
            {"budget_ms": os.environ.get("C1_QUERY_TIME_BUDGET_MS"), "results": results}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
