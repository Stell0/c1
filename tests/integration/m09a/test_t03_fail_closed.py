"""M09a-T03: a failed or unbounded binding scan returns no partial selection."""

from __future__ import annotations

import asyncio
import functools
import time

import pytest

from c1.authorization import plane as plane_module
from c1.query.plan import QueryPlanError
from scripts.stack import compose
from tests.integration.m03.conftest import live_case
from tests.integration.m09a.conftest import provision_matrix


def test_t03_scan_outage_and_page_cap_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plane_module, "use_scan", lambda _count, _n, **_kw: True)

    async def run() -> None:
        async with live_case() as case:
            _shared, _other, ids = await provision_matrix(case, 120)
            plane = case.runtime.plane
            alice = await case.principal("alice")

            # More than one page of tuples with a one-page cap: deny everything.
            fga = case.runtime.fga
            capped = functools.partial(type(fga).scan_bindings, fga, max_pages=1)
            monkeypatch.setattr(fga, "scan_bindings", capped)
            decisions = await plane.check_many(alice, ids["plain"], "can_read")
            assert {d.reason for d in decisions.values()} == {"security_unavailable"}
            with pytest.raises(QueryPlanError) as raised:
                await case.runtime.query.selection(alice, deadline=time.monotonic() + 30)
            assert raised.value.status == 503
            monkeypatch.undo()
            monkeypatch.setattr(plane_module, "use_scan", lambda _count, _n, **_kw: True)

            # OpenFGA paused during the scan: deny, then recover after unpause.
            await asyncio.to_thread(compose, ["pause", "openfga"])
            try:
                decisions = await plane.check_many(alice, ids["plain"], "can_read")
                assert {d.reason for d in decisions.values()} == {"security_unavailable"}
            finally:
                await asyncio.to_thread(compose, ["unpause", "openfga"])
            for _ in range(30):
                decisions = await plane.check_many(alice, ids["plain"], "can_read")
                if all(d.allowed for d in decisions.values()):
                    break
                await asyncio.sleep(1)
            assert all(d.allowed for d in decisions.values())

    asyncio.run(run())
