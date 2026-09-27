"""M03-T04: current security state authorizes old knowledge revisions."""

from __future__ import annotations

import asyncio

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m03.conftest import entity_record, live_case, resource_path


def test_t04_old_revision_loses_old_scope_access_after_rescope() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await case.scope("M03-T04 shared")
            restricted = await case.scope("M03-T04 restricted")
            await case.grant(shared, "alice", "reader")
            await case.grant(restricted, "frank", "access_admin")

            identifier = entity_record(label="Historical v1").id
            old = entity_record(
                identifier, label="Historical v1", scope_hint="urn:c1:scope:" + shared
            )
            creation = await case.provision(old, shared)
            old_revision = creation["revision"]
            updated = entity_record(
                identifier, label="Historical v2", scope_hint="urn:c1:scope:" + shared
            )
            new_revision = await case.request(
                "PUT", resource_path(identifier), json={"record": updated.model_dump(mode="json")}
            )
            assert new_revision.status_code == 200, new_revision.text
            assert new_revision.json()["revision"] != old_revision

            path = resource_path(identifier)
            before = await case.request("GET", path + "?revision=" + old_revision, actor="alice")
            assert before.status_code == 200, before.text
            assert before.json() == old.model_dump(mode="json")

            proposed = await case.request(
                "POST",
                f"/v1/access-scopes/{restricted}/bindings",
                json={"resource_id": identifier},
            )
            assert proposed.status_code == 200, proposed.text
            operation_id = proposed.json()["id"]
            assert (await case.request("GET", path, actor="alice")).status_code == 200
            approved = await case.request(
                "POST", f"/v1/security-operations/{operation_id}/approve", actor="frank"
            )
            assert approved.status_code == 200, approved.text
            applied = await case.request("POST", f"/v1/security-operations/{operation_id}/apply")
            assert applied.status_code == 200, applied.text
            assert applied.json()["state"] == "applied"

            assert await case.fga.bindings(resource_object(identifier)) == [
                scope_object(restricted)
            ]
            assert (await case.request("GET", path, actor="alice")).status_code == 404
            assert (
                await case.request("GET", path + "?revision=" + old_revision, actor="alice")
            ).status_code == 404
            admin_old = await case.request("GET", path + "?revision=" + old_revision)
            assert admin_old.status_code == 200, admin_old.text
            assert admin_old.json()["properties"]["urn:c1:ns:core#provisionedScopeHint"] == [
                "urn:c1:scope:" + shared
            ]

    asyncio.run(run())
