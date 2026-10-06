"""M09a-T02: no decision survives a security change between or during checks."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import pytest

from c1.authorization import plane as plane_module
from c1.authorization.models import Operation
from c1.query.plan import QueryPlanError
from tests.integration.m03.conftest import live_case
from tests.integration.m09a.conftest import provision_matrix


def test_t02_revocation_and_changes_take_effect_without_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plane_module, "use_scan", lambda _count, _n, **_kw: True)

    async def run() -> None:
        async with live_case() as case:
            shared, _other, ids = await provision_matrix(case, 30)
            plane = case.runtime.plane
            alice = await case.principal("alice")
            assert all(
                d.allowed
                for d in (await plane.check_many(alice, ids["plain"], "can_read")).values()
            )

            # Between plan build and finalize: the M05 restart contract is unchanged.
            plan, _ = await case.runtime.query.selection(alice, deadline=time.monotonic() + 30)
            assert set(ids["plain"]) <= set(plan.authorized_ids)
            alice_id = (await case.principal("alice")).id
            revoked = await case.request(
                "DELETE",
                f"/v1/access-scopes/{quote(shared, safe='')}/members/{quote(alice_id, safe='')}",
                params={"role": "reader"},
            )
            assert revoked.status_code == 200, revoked.text
            with pytest.raises(QueryPlanError) as raised:
                await case.runtime.query.planner.finalize(
                    alice, plan, deadline=time.monotonic() + 30
                )
            assert raised.value.status == 409

            # Between requests: the next decision denies; nothing was retained.
            decisions = await plane.check_many(alice, ids["plain"], "can_read")
            assert not any(d.allowed for d in decisions.values())
            await case.grant(shared, "alice", "reader")

            # During a scan: a journal write mid-check yields a revision change.
            original = case.runtime.fga.scan_bindings

            async def scan_with_write(**kwargs: Any) -> dict[str, list[str]]:
                result: dict[str, list[str]] = await original(**kwargs)
                marker = Operation(
                    id="m09a-midscan",
                    kind="probe_revision",
                    actor="user:test",
                    target="none",
                    state="applied",
                    created="2026-10-01T00:00:00Z",
                    updated="2026-10-01T00:00:00Z",
                )
                await case.journal.save_many(
                    [("Operation", marker.id, marker.model_dump(mode="json"))]
                )
                return result

            monkeypatch.setattr(case.runtime.fga, "scan_bindings", scan_with_write)
            decisions = await plane.check_many(alice, ids["plain"], "can_read")
            assert {d.reason for d in decisions.values()} == {"security_revision_changed"}

    asyncio.run(run())
