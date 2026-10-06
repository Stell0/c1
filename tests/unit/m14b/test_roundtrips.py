"""M14b D1: per-request backend counts, backend time and phase time."""

from __future__ import annotations

import asyncio

from c1 import roundtrips


def test_phases_and_backends_accumulate_per_request_and_across_tasks() -> None:
    @roundtrips.phased("work")
    async def work() -> int:
        with roundtrips.timed("openfga"):
            await asyncio.sleep(0.01)
        return 1

    async def run() -> None:
        roundtrips.begin()
        assert list(await asyncio.gather(work(), work())) == [1, 1]
        with roundtrips.phase("sync"):
            pass
        counts = roundtrips.current()
        timings = roundtrips.timings()
        assert counts == {"terminus": 0, "openfga": 2}
        assert timings["backend_ms"]["openfga"] >= 20
        assert set(timings["phases_ms"]) == {"work", "sync"}

    asyncio.run(run())


def test_no_record_outside_a_request() -> None:
    async def run() -> None:
        with roundtrips.timed("terminus"), roundtrips.phase("x"):
            pass
        assert roundtrips.current() is None
        assert roundtrips.timings() == {}

    asyncio.run(run())
