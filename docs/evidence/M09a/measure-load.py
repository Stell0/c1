"""Time one software-integration load and lookups; count OpenFGA calls (M09a evidence).

Run from a checkout's root with C1_STACK=1. It records, per producer run, the
wall-clock time and the OpenFGA requests by endpoint, then three lookups.
No profiler is attached, so times are directly comparable between checkouts.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path.cwd()))

import c1.authorization.fga as fgamod  # noqa: E402
from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.software import CaseLoader, fresh_tokens  # noqa: E402

calls: Counter[str] = Counter()
_original = fgamod.FGA._request


async def _counted(self: Any, method: str, path: str, **kwargs: Any) -> Any:
    calls[path.rsplit("/", 1)[-1]] += 1
    return await _original(self, method, path, **kwargs)


fgamod.FGA._request = _counted  # type: ignore[method-assign]


async def main() -> None:
    out: list[dict[str, Any]] = []
    async with live_case() as case:
        fresh_tokens(case)
        loader = CaseLoader(case)
        inputs = sp.load_inputs()
        start = time.monotonic()
        principals = await sp.install_and_prepare(loader, inputs.fixture)
        for run in sp.Planner(inputs, principals).runs():
            calls.clear()
            t = time.monotonic()
            await sp.apply_run(loader, run)
            out.append({"run": run.key, "s": round(time.monotonic() - t, 2), "fga": dict(calls)})
        total = round(time.monotonic() - start, 1)
        body = {"target": {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}, "limit": 200}
        lookups = []
        for _ in range(3):
            calls.clear()
            t = time.monotonic()
            response = await case.request("POST", "/v1/software/lookup", actor="carol", json=body)
            lookups.append(
                {
                    "status": response.status_code,
                    "s": round(time.monotonic() - t, 2),
                    "fga": dict(calls),
                }
            )
    print(json.dumps({"load_s": total, "runs": out, "lookups": lookups}))


asyncio.run(main())
