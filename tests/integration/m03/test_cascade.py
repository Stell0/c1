"""An approved scope move is stale when its inherited child set changes."""

from __future__ import annotations

import asyncio

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m03.conftest import document_record, live_case, part_record, resource_path


def test_stale_approved_cascade_refuses_mutation_and_explicit_child_stays_put() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await case.scope("M03 cascade shared")
            destination = await case.scope("M03 cascade destination")
            separate = await case.scope("M03 explicit child scope")
            await case.grant(shared, "alice", "reader")
            await case.grant(separate, "alice", "reader")
            await case.grant(destination, "frank", "access_admin")

            parent = document_record()
            explicit_child = part_record(parent.id)
            await case.provision(parent, shared)
            await case.provision(explicit_child, separate)
            assert (
                await case.request("GET", resource_path(parent.id), actor="alice")
            ).status_code == 200
            assert (
                await case.request("GET", resource_path(explicit_child.id), actor="alice")
            ).status_code == 200

            proposed = await case.request(
                "POST",
                f"/v1/access-scopes/{destination}/bindings",
                json={"resource_id": parent.id},
            )
            assert proposed.status_code == 200, proposed.text
            stale_id = proposed.json()["id"]
            assert proposed.json()["targets"] == [parent.id]
            approved = await case.request(
                "POST", f"/v1/security-operations/{stale_id}/approve", actor="frank"
            )
            assert approved.status_code == 200, approved.text

            inherited_child = part_record(parent.id)
            inherited = await case.request(
                "POST",
                "/v1/probe/resources",
                json={
                    "record": inherited_child.model_dump(mode="json"),
                    "inherited_from": parent.id,
                },
            )
            assert inherited.status_code == 201, inherited.text
            binding = await case.journal.get("Binding", inherited_child.id)
            assert binding is not None
            assert binding["scope_id"] == shared
            assert binding["inherited_from"] == parent.id

            before_head = await case.journal.head()
            before_log = await case.journal._storage.log()
            before_parent = await case.fga.bindings(resource_object(parent.id))
            before_inherited = await case.fga.bindings(resource_object(inherited_child.id))
            rejected = await case.request("POST", f"/v1/security-operations/{stale_id}/apply")
            assert rejected.status_code == 409, rejected.text
            assert await case.journal.head() == before_head
            assert await case.journal._storage.log() == before_log
            assert await case.fga.bindings(resource_object(parent.id)) == before_parent
            assert await case.fga.bindings(resource_object(inherited_child.id)) == before_inherited
            assert (
                await case.request("GET", resource_path(parent.id), actor="alice")
            ).status_code == 200
            assert (
                await case.request("GET", resource_path(inherited_child.id), actor="alice")
            ).status_code == 200

            refreshed = await case.request(
                "POST",
                f"/v1/access-scopes/{destination}/bindings",
                json={"resource_id": parent.id},
            )
            assert refreshed.status_code == 200, refreshed.text
            current_id = refreshed.json()["id"]
            assert set(refreshed.json()["targets"]) == {parent.id, inherited_child.id}
            approved_again = await case.request(
                "POST", f"/v1/security-operations/{current_id}/approve", actor="frank"
            )
            assert approved_again.status_code == 200, approved_again.text
            applied = await case.request("POST", f"/v1/security-operations/{current_id}/apply")
            assert applied.status_code == 200, applied.text
            assert applied.json()["state"] == "applied"
            assert await case.fga.bindings(resource_object(parent.id)) == [
                scope_object(destination)
            ]
            assert await case.fga.bindings(resource_object(inherited_child.id)) == [
                scope_object(destination)
            ]
            assert await case.fga.bindings(resource_object(explicit_child.id)) == [
                scope_object(separate)
            ]
            assert (
                await case.request("GET", resource_path(parent.id), actor="alice")
            ).status_code == 404
            assert (
                await case.request("GET", resource_path(inherited_child.id), actor="alice")
            ).status_code == 404
            assert (
                await case.request("GET", resource_path(explicit_child.id), actor="alice")
            ).status_code == 200

    asyncio.run(run())
