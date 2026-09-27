"""M03-T02: each scope and instance capability is independent."""

from __future__ import annotations

import asyncio

from tests.integration.m03.conftest import entity_record, live_case, resource_path


def test_t02_reader_contributor_reviewer_operator_and_admin_are_separate() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await case.scope("M03-T02 synthetic scope")
            await case.grant(scope, "alice", "reader")
            await case.grant(scope, "bob", "contributor")
            await case.grant(scope, "carol", "reviewer")

            alice = await case.principal("alice")
            bob = await case.principal("bob")
            carol = await case.principal("carol")
            dave = await case.principal("dave")
            assert (await case.runtime.plane.check_scope(alice, "read", scope)).allowed
            assert not (await case.runtime.plane.check_scope(alice, "create", scope)).allowed
            assert not (await case.runtime.plane.check_scope(alice, "review", scope)).allowed
            assert (await case.runtime.plane.check_scope(bob, "contribute", scope)).allowed
            assert not (await case.runtime.plane.check_scope(bob, "review", scope)).allowed
            assert (await case.runtime.plane.check_scope(carol, "review", scope)).allowed
            assert not (await case.runtime.plane.check_scope(carol, "read", scope)).allowed
            assert (await case.runtime.plane.check_instance(dave, "operator")).allowed
            assert not (await case.runtime.plane.check_scope(dave, "read", scope)).allowed

            record = entity_record(label="Permission split")
            await case.provision(record, scope)
            path = resource_path(record.id)
            assert (await case.request("GET", path, actor="alice")).status_code == 200
            assert (await case.request("GET", path, actor="carol")).status_code == 404
            assert (await case.request("GET", path, actor="dave")).status_code == 404

            denied = await case.request(
                "POST",
                f"/v1/access-scopes/{scope}/members",
                actor="carol",
                json={"member": alice.id, "role": "reader"},
            )
            assert denied.status_code == 403

            await case.grant(scope, "carol", "reader")
            assert (await case.request("GET", path, actor="carol")).status_code == 200
            removed = await case.request(
                "DELETE",
                f"/v1/access-scopes/{scope}/members/{alice.id}?role=reader",
            )
            assert removed.status_code == 200, removed.text
            assert (await case.request("GET", path, actor="alice")).status_code == 404

    asyncio.run(run())
