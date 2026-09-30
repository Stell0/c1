"""Latency distribution of software requests after a fresh software-integration load.

Repeats the M08-T02 request mix (lookup, historical lookup, branch resolve) and
records each duration. The budget is raised to 30,000 ms only for measurement.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.software import load  # noqa: E402

TARGET = {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}
RESOLVE = {
    "branches": [{"repository": sp.repository_id("ledger"), "branch": "main"}],
    "as_of": "2026-01-20T00:00:00Z",
}


async def main() -> None:
    samples: dict[str, list[float]] = {"lookup": [], "historical_lookup": [], "resolve": []}
    async with live_case() as case:
        loaded = await load(case)
        early = next(r["revision_after"] for r in loaded["runs"] if r["run"] == "scip/b1")
        for _ in range(15):
            for name, path, body in (
                ("lookup", "/v1/software/lookup", {"target": TARGET, "limit": 200}),
                (
                    "historical_lookup",
                    "/v1/software/lookup",
                    {"target": TARGET, "limit": 200, "revision": early},
                ),
                ("resolve", "/v1/software/targets/resolve", RESOLVE),
            ):
                start = time.monotonic()
                response = await case.request("POST", path, actor="carol", json=body)
                samples[name].append(round(time.monotonic() - start, 3))
                assert response.status_code == 200, response.text
    print(
        json.dumps(
            {
                name: {
                    "n": len(values),
                    "median": statistics.median(values),
                    "max": max(values),
                    "min": min(values),
                    "values": values,
                }
                for name, values in samples.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
