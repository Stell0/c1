"""Real BatchCheck and fresh re-scope authority contracts."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m03.conftest import entity_record, live_case


def test_native_batch_check_and_plane_chunk_over_fifty_resources() -> None:
    async def run() -> None:
        async with live_case() as case:
            visible_scope = await case.scope("M03 batch visible")
            hidden_scope = await case.scope("M03 batch hidden")
            await case.grant(visible_scope, "alice", "reader")
            visible = entity_record(label="Batch visible")
            hidden = entity_record(label="Batch hidden")
            await case.provision(visible, visible_scope)
            await case.provision(hidden, hidden_scope)
            identifiers = [
                visible.id,
                *[f"urn:c1:probe:missing-batch-{index}" for index in range(49)],
                hidden.id,
            ]
            assert len(identifiers) == 51
            alice = await case.principal("alice")
            checks = [
                (alice.id, "can_read", resource_object(identifier)) for identifier in identifiers
            ]
            native = await case.fga.batch_check(checks)
            assert native == [True, *([False] * 50)]

            decisions = await case.runtime.plane.batch_read(alice, identifiers)
            assert list(decisions) == identifiers
            assert decisions[visible.id].allowed
            assert all(not decisions[identifier].allowed for identifier in identifiers[1:])

    asyncio.run(run())


def test_rescope_authority_is_rechecked_before_any_apply_mutation() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await case.scope("M03 authority shared")
            destination = await case.scope("M03 authority destination")
            await case.grant(destination, "frank", "access_admin")
            await case.grant(shared, "frank", "access_admin")
            actor = await case.principal("erin")
            approver = await case.principal("frank")
            record = entity_record(label="Authority target one")
            await case.provision(record, shared)
            path = f"/v1/access-scopes/{destination}/bindings"

            before_denied = await case.journal.head()
            before_denied_log = await case.journal._storage.log()
            denied = await case.request("POST", path, actor="bob", json={"resource_id": record.id})
            assert denied.status_code == 403, denied.text
            assert await case.journal.head() == before_denied
            assert await case.journal._storage.log() == before_denied_log
            assert await case.fga.bindings(resource_object(record.id)) == [scope_object(shared)]

            proposal = await case.request("POST", path, json={"resource_id": record.id})
            assert proposal.status_code == 200, proposal.text
            operation_id = proposal.json()["id"]
            approved_path = f"/v1/security-operations/{operation_id}/approve"
            apply_path = f"/v1/security-operations/{operation_id}/apply"
            before_approval = await case.journal.head()
            before_approval_log = await case.journal._storage.log()
            premature = await case.request("POST", apply_path)
            assert premature.status_code == 409, premature.text
            self_approval = await case.request("POST", approved_path)
            assert self_approval.status_code == 403, self_approval.text
            assert await case.journal.head() == before_approval
            assert await case.journal._storage.log() == before_approval_log
            approval = await case.request("POST", approved_path, actor="frank")
            assert approval.status_code == 200, approval.text
            assert approval.json()["state"] == "approved"

            # Revoking the original actor after approval must defeat an executor
            # who still has current admin authority in both scopes.
            revoke_actor = await case.request(
                "DELETE",
                f"/v1/access-scopes/{destination}/members/{quote(actor.id, safe='')}"
                "?role=access_admin",
            )
            assert revoke_actor.status_code == 200, revoke_actor.text
            actor_head = await case.journal.head()
            actor_log = await case.journal._storage.log()
            actor_denied = await case.request("POST", apply_path, actor="frank")
            assert actor_denied.status_code == 403, actor_denied.text
            assert await case.journal.head() == actor_head
            assert await case.journal._storage.log() == actor_log
            first_state = await case.journal.get("Operation", operation_id)
            assert first_state is not None and first_state["state"] == "approved"
            assert await case.fga.bindings(resource_object(record.id)) == [scope_object(shared)]

            # Restore the actor through a currently authorized administrator,
            # then revoke the distinct approver for a second approved operation.
            restore = await case.request(
                "POST",
                f"/v1/access-scopes/{destination}/members",
                actor="frank",
                json={"member": actor.id, "role": "access_admin"},
            )
            assert restore.status_code == 200, restore.text
            second = entity_record(label="Authority target two")
            await case.provision(second, shared)
            second_proposal = await case.request("POST", path, json={"resource_id": second.id})
            assert second_proposal.status_code == 200, second_proposal.text
            second_id = second_proposal.json()["id"]
            second_approval = await case.request(
                "POST", f"/v1/security-operations/{second_id}/approve", actor="frank"
            )
            assert second_approval.status_code == 200, second_approval.text
            revoke_approver = await case.request(
                "DELETE",
                f"/v1/access-scopes/{destination}/members/{quote(approver.id, safe='')}"
                "?role=access_admin",
            )
            assert revoke_approver.status_code == 200, revoke_approver.text
            approver_head = await case.journal.head()
            approver_log = await case.journal._storage.log()
            approver_denied = await case.request(
                "POST", f"/v1/security-operations/{second_id}/apply"
            )
            assert approver_denied.status_code == 403, approver_denied.text
            assert await case.journal.head() == approver_head
            assert await case.journal._storage.log() == approver_log
            second_state = await case.journal.get("Operation", second_id)
            assert second_state is not None and second_state["state"] == "approved"
            assert await case.fga.bindings(resource_object(second.id)) == [scope_object(shared)]

    asyncio.run(run())
