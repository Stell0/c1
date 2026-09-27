"""M04-T03: validation and apply enforce whole-ChangeSet scope authority."""

from __future__ import annotations

import asyncio
import uuid

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m04.conftest import (
    action,
    changeset_path,
    create,
    live_case,
    new_changeset,
    new_entity,
    seeded_scope,
)


def test_t03_two_scope_commit_and_late_revocation_are_atomic() -> None:
    async def run() -> None:
        async with live_case() as case:
            first = await seeded_scope(case, "M04-T03 first")
            second = await case.scope("M04-T03 second")
            await case.grant(second, "carol", "reviewer")
            await case.grant(second, "carol", "reader")
            left = new_entity("First scope record")
            right = new_entity("Second scope record")
            before = len(await case.knowledge.log())
            proposed = await new_changeset(case, [create(left, first), create(right, second)])
            denied = await case.request(
                "POST", changeset_path(proposed["id"], "submit"), actor="bob"
            )
            assert denied.status_code == 403, denied.text
            report = await case.request(
                "GET", changeset_path(proposed["id"], "validation"), actor="bob"
            )
            assert report.status_code == 200, report.text
            preview = report.json()["permission_preview"]
            assert preview[0]["allowed"] is True
            assert preview[1]["allowed"] is False
            assert len(await case.knowledge.log()) == before
            assert await case.fga.bindings(resource_object(right.id)) == []

            await case.grant(second, "bob", "creator")
            await case.grant(second, "bob", "reader")
            await case.grant(second, "bob", "contributor")
            revised = await case.request(
                "PUT",
                changeset_path(proposed["id"], "operations"),
                actor="bob",
                json={"operations": [create(left, first), create(right, second)]},
            )
            assert revised.status_code == 200, revised.text
            assert revised.json()["state"] == "draft"
            await action(case, proposed["id"], "submit")
            current = await case.request("GET", changeset_path(proposed["id"]), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, proposed["id"], "validate")
            await action(case, proposed["id"], "approve", actor="carol")
            result = await action(case, proposed["id"], "apply", actor="carol")
            assert result["state"] == "applied"
            assert len(await case.knowledge.log()) == before + 1
            for record, scope in ((left, first), (right, second)):
                assert await case.fga.bindings(resource_object(record.id)) == [scope_object(scope)]
                binding = await case.journal.get("Binding", record.id)
                assert binding is not None and binding["state"] == "active"
            activities = [
                record
                for record in await case.knowledge.read_records(case.runtime.registry)
                if "http://www.w3.org/ns/prov#Activity" in record.types
                and any(
                    getattr(value, "lexical", None) == "changeset-apply"
                    for value in record.properties.get("urn:c1:ns:core#method", [])
                )
            ]
            assert len(activities) == 2
            activity_scopes = [
                (await case.fga.bindings(resource_object(activity.id)))[0]
                for activity in activities
            ]
            assert sorted(activity_scopes) == sorted([scope_object(first), scope_object(second)])

            third = new_entity("Late revocation first")
            fourth = new_entity("Late revocation second")
            pending = await new_changeset(case, [create(third, first), create(fourth, second)])
            await action(case, pending["id"], "submit")
            current = await case.request("GET", changeset_path(pending["id"]), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, pending["id"], "validate")
            await action(case, pending["id"], "approve", actor="carol")
            carol = await case.principal("carol")
            revoked = await case.request(
                "DELETE",
                f"/v1/access-scopes/{second}/members/{carol.id}?role=reviewer",
            )
            assert revoked.status_code == 200, revoked.text
            unchanged = len(await case.knowledge.log())
            apply = await case.request(
                "POST",
                changeset_path(pending["id"], "apply"),
                actor="carol",
                headers={"Idempotency-Key": uuid.uuid4().hex},
            )
            assert apply.status_code == 403, apply.text
            assert len(await case.knowledge.log()) == unchanged
            for record in (third, fourth):
                assert await case.fga.bindings(resource_object(record.id)) == []

    asyncio.run(run())
