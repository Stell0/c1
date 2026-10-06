"""M14b-T02: finalize through the OpenFGA change log (D3, ADR-0026).

Each security change is written to OpenFGA directly, with no journal write,
so only the change log can reveal it to finalize.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from c1 import roundtrips
from c1.authorization.fga import resource_object, scope_object
from c1.query.plan import QueryPlanError
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m09a.conftest import provision_matrix


async def _plan(case: LiveCase, name: str):  # type: ignore[no-untyped-def]
    principal = await case.principal(name)
    plan, _ = await case.runtime.query.selection(principal, deadline=time.monotonic() + 30)
    return principal, plan


async def _finalize_openfga_calls(case: LiveCase, name: str) -> int:
    principal, plan = await _plan(case, name)
    counts = roundtrips.begin()
    await case.runtime.query.planner.finalize(principal, plan, deadline=time.monotonic() + 30)
    return counts["openfga"]


def test_t02_change_log_shortcut_and_every_change_forces_fresh_reads() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared, other, ids = await provision_matrix(case, 12)
            fga = case.runtime.fga
            assert fga.read_model_verified
            assert fga.change_log_verified  # startup probe: no change-log horizon
            alice = await case.principal("alice")
            reader = (alice.id, "reader", scope_object(shared))
            assert reader in await fga.read(relation="reader", object=scope_object(shared))

            # Unchanged store: finalize reads only the change log.
            assert await _finalize_openfga_calls(case, "alice") == 1

            # Unrelated change: fresh reads, same result, no restart.
            bob = await case.principal("bob")
            unrelated = (bob.id, "reviewer", scope_object(other))
            principal, plan = await _plan(case, "alice")
            await fga.write([unrelated])
            counts = roundtrips.begin()
            await case.runtime.query.planner.finalize(
                principal, plan, deadline=time.monotonic() + 30
            )
            assert counts["openfga"] > 1
            await fga.write([], [unrelated])

            # 1. Reader removal between build and finalize.
            principal, plan = await _plan(case, "alice")
            assert set(ids["plain"]) <= set(plan.authorized_ids)
            await fga.write([], [reader])
            with pytest.raises(QueryPlanError) as raised:
                await case.runtime.query.planner.finalize(
                    principal, plan, deadline=time.monotonic() + 30
                )
            assert raised.value.status == 409
            await fga.write([reader])

            # 2. Re-binding one resource to another scope.
            moved = ids["plain"][0]
            old = (scope_object(shared), "bound_to", resource_object(moved))
            new = (scope_object(other), "bound_to", resource_object(moved))
            principal, plan = await _plan(case, "alice")
            assert moved in plan.authorized_ids
            await fga.write([new], [old])
            with pytest.raises(QueryPlanError) as raised:
                await case.runtime.query.planner.finalize(
                    principal, plan, deadline=time.monotonic() + 30
                )
            assert raised.value.status == 409
            await fga.write([old], [new])

            # 3. Group membership removal: alice reads only through a group.
            group_reader = ("group:m14b#member", "reader", scope_object(shared))
            member = (alice.id, "member", "group:m14b")
            await fga.write([group_reader, member], [reader])
            principal, plan = await _plan(case, "alice")
            assert set(ids["plain"]) <= set(plan.authorized_ids)
            await fga.write([], [member])
            with pytest.raises(QueryPlanError) as raised:
                await case.runtime.query.planner.finalize(
                    principal, plan, deadline=time.monotonic() + 30
                )
            assert raised.value.status == 409
            await fga.write([reader], [group_reader])

            # The next request sees the restored state and the shortcut again.
            assert await _finalize_openfga_calls(case, "alice") == 1

    asyncio.run(run())
