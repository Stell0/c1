"""M09a-T01: batched decisions equal the legacy single-resource decisions."""

from __future__ import annotations

import asyncio

import pytest

from c1.authorization import plane as plane_module
from c1.authorization.fga import resource_object, scope_object
from c1.authorization.models import Binding, Operation
from tests.integration.m03.conftest import live_case
from tests.integration.m09a.conftest import legacy_decision, provision_matrix


@pytest.mark.parametrize("strategy", ["scan", "per-resource"])
def test_t01_batched_decisions_equal_legacy(strategy: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plane_module, "use_scan", lambda _count, _n, **_kw: strategy == "scan")

    async def run() -> None:
        async with live_case() as case:
            shared, other, ids = await provision_matrix(case, 40)
            fga = case.fga
            await fga.write(
                [], deletes=[(scope_object(shared), "bound_to", resource_object(ids["missing"]))]
            )
            await fga.write(
                [(scope_object(other), "bound_to", resource_object(ids["extra_known"]))]
            )
            await fga.write(
                [("scope:never_created", "bound_to", resource_object(ids["extra_unknown"]))]
            )
            value = await case.journal.get("Binding", ids["revoked"])
            assert value is not None
            binding = Binding.model_validate(value)
            binding.state = "revoked"
            await case.journal.save_many(
                [("Binding", ids["revoked"], binding.model_dump(mode="json"))]
            )
            pending = Operation(
                id="m09a-pending",
                kind="rescope",
                actor="user:test",
                target=ids["pending"],
                state="pending",
                targets=[ids["pending"]],
                created="2026-10-01T00:00:00Z",
                updated="2026-10-01T00:00:00Z",
            )
            await case.journal.save_many(
                [("Operation", pending.id, pending.model_dump(mode="json"))]
            )
            alice = await case.principal("alice")
            all_ids = [*ids["plain"], *(ids[k] for k in ids if k != "plain"), "urn:c1:probe:never"]
            legacy = {i: await legacy_decision(case, alice, i) for i in all_ids}
            batched = await case.runtime.plane.check_many(alice, all_ids, "can_read")
            single = {i: await case.runtime.plane.check_read(alice, i) for i in all_ids}
            assert batched == legacy == single
            assert {legacy[ids[k]].reason for k in ("missing", "extra_known", "extra_unknown")} == {
                "inconsistent_binding"
            }
            assert legacy[ids["revoked"]].reason == "inactive_binding"
            assert legacy[ids["pending"]].reason == "pending_security_operation"
            assert legacy[ids["denied"]].reason == "permission_denied"
            assert all(legacy[i].allowed for i in ids["plain"])
            # The resource route's 404s are unchanged for every fault kind.
            for kind in ("missing", "extra_known", "extra_unknown", "revoked", "pending", "denied"):
                response = await case.request(
                    "GET", "/v1/probe/resources/" + ids[kind].replace(":", "%3A"), actor="alice"
                )
                assert response.status_code == 404, (kind, response.text)

    asyncio.run(run())
