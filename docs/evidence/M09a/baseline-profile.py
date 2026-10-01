import asyncio
import cProfile
import io
import json
import pstats
import sys
import time
from collections import Counter

sys.path.insert(0, "/home/tux/personalbuild/c1")
import c1.authorization.fga as fgamod
from scripts import software_producer as sp
from tests.integration.m03.conftest import live_case
from tests.integration.software import CaseLoader, fresh_tokens

calls = Counter()
orig = fgamod.FGA._request


async def counted(self, method, path, **kw):
    calls[path.rsplit("/", 1)[-1]] += 1
    return await orig(self, method, path, **kw)


fgamod.FGA._request = counted


async def main():
    async with live_case() as case:
        fresh_tokens(case)
        loader = CaseLoader(case)
        inputs = sp.load_inputs()
        principals = await sp.install_and_prepare(loader, inputs.fixture)
        runs = sp.Planner(inputs, principals).runs()
        out = []
        prof = cProfile.Profile()
        for run in runs:
            calls.clear()
            t = time.monotonic()
            if run.key == "calls/a2":
                prof.enable()
            await sp.apply_run(loader, run)
            if run.key == "calls/a2":
                prof.disable()
            out.append(
                {
                    "run": run.key,
                    "s": round(time.monotonic() - t, 1),
                    "records": len(run.records),
                    "fga": dict(calls),
                }
            )
        # one lookup's FGA calls
        calls.clear()
        t = time.monotonic()
        await case.request(
            "POST",
            "/v1/software/lookup",
            actor="carol",
            json={
                "target": {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]},
                "limit": 200,
            },
        )
        out.append({"run": "lookup", "s": round(time.monotonic() - t, 1), "fga": dict(calls)})
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(60)
        print(json.dumps({"runs": out, "profile_calls_a2": s.getvalue().splitlines()}))


asyncio.run(main())
