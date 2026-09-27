"""M04-T06: restoring old content keeps current binding and historical denial."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m04.conftest import (
    action,
    changeset_path,
    entity_record,
    live_case,
    new_changeset,
    path,
    replace,
    seeded_scope,
)


def test_t06_restore_cannot_resurrect_old_scope_access() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M04-T06 shared")
            restricted = await case.scope("M04-T06 restricted")
            for person, role in (
                ("bob", "contributor"),
                ("bob", "reader"),
                ("carol", "reviewer"),
                ("carol", "reader"),
            ):
                await case.grant(restricted, person, role)
            await case.grant(restricted, "frank", "access_admin")
            identifier = entity_record(label="Version one").id
            v1 = entity_record(identifier, label="Version one")
            created = await case.provision(v1, shared)
            rev1 = created["revision"]
            v2 = entity_record(identifier, label="Version two")
            update = await case.request(
                "PUT",
                "/v1/probe/resources/" + quote(identifier, safe=""),
                json={"record": v2.model_dump(mode="json")},
            )
            assert update.status_code == 200, update.text
            rev2 = update.json()["revision"]
            proposed = await case.request(
                "POST",
                f"/v1/access-scopes/{restricted}/bindings",
                json={"resource_id": identifier},
            )
            assert proposed.status_code == 200, proposed.text
            operation_id = proposed.json()["id"]
            assert (
                await case.request(
                    "POST", f"/v1/security-operations/{operation_id}/approve", actor="frank"
                )
            ).status_code == 200
            assert (
                await case.request("POST", f"/v1/security-operations/{operation_id}/apply")
            ).status_code == 200
            assert await case.fga.bindings(resource_object(identifier)) == [
                scope_object(restricted)
            ]

            restoration = await new_changeset(
                case,
                [replace(v1, "Restore the reviewed first version")],
                restores_from_revision=rev1,
            )
            await action(case, restoration["id"], "submit")
            current = await case.request("GET", changeset_path(restoration["id"]), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, restoration["id"], "validate")
            await action(case, restoration["id"], "approve", actor="carol")
            assert (await action(case, restoration["id"], "apply", actor="carol"))[
                "state"
            ] == "applied"
            current_resource = await case.request("GET", path(identifier), actor="bob")
            assert current_resource.status_code == 200, current_resource.text
            assert current_resource.json() == v1.model_dump(mode="json")
            assert await case.fga.bindings(resource_object(identifier)) == [
                scope_object(restricted)
            ]
            for denied_path in (
                path(identifier),
                path(identifier) + "?revision=" + rev1,
                path(identifier) + "?revision=" + rev2,
                changeset_path(restoration["id"]),
                changeset_path(restoration["id"], "validation"),
                "/v1/history?resource_id=" + quote(identifier, safe=""),
            ):
                assert (await case.request("GET", denied_path, actor="alice")).status_code == 404

            altered = entity_record(identifier, label="Falsely claimed version one")
            bad = await new_changeset(
                case,
                [replace(altered)],
                restores_from_revision=rev1,
            )
            rejected = await action(case, bad["id"], "submit")
            if rejected["state"] == "submitted":
                rejected = await action(case, bad["id"], "validate")
            assert rejected["state"] == "rejected"
            report = await case.request("GET", changeset_path(bad["id"], "validation"), actor="bob")
            assert "C1-CS-030" in {entry["code"] for entry in report.json()["diagnostics"]}

    asyncio.run(run())
