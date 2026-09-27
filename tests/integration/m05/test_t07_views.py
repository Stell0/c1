"""M05-T07: project views narrow the shared authorized repository."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m04.conftest import (
    entity_record,
    live_case,
    new_changeset,
    replace,
    reviewed_apply,
    seeded_scope,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]

PROJECT_A = "urn:c1:probe:project-m05-t07-a"
PROJECT_B = "urn:c1:test:project:b"


def _observation(body: dict[str, Any]) -> dict[str, Any]:
    # A hidden write advances the shared content revision. The authorized
    # selection, count, and explanations must remain unchanged.
    return {key: body[key] for key in ("items", "count", "explain", "indeterminate", "next_cursor")}


def test_t07_project_reference_narrows_without_copy_or_grant() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M05-T07 shared")
            restricted = await case.scope("M05-T07 restricted")
            for person, role in (
                ("bob", "creator"),
                ("bob", "contributor"),
                ("bob", "reader"),
                ("carol", "reviewer"),
                ("carol", "reader"),
            ):
                await case.grant(restricted, person, role)

            visible_a = entity_record(label="Visible A", project=PROJECT_A)
            visible_b = entity_record(label="Visible B", project=PROJECT_B)
            hidden = entity_record(label="Restricted member", project=PROJECT_B)
            for record in (visible_a, visible_b):
                await case.provision(record, shared)
            await case.provision(hidden, restricted)

            async def search(actor: str, project: str | None = None) -> dict[str, Any]:
                params = {"project_ref": project} if project is not None else None
                response = await case.request("GET", "/v1/entities", actor=actor, params=params)
                assert response.status_code == 200, response.text
                body = response.json()
                assert isinstance(body, dict)
                return body

            alice_all = await search("alice")
            alice_a = await search("alice", PROJECT_A)
            alice_b = await search("alice", PROJECT_B)
            assert [item["id"] for item in alice_all["items"]] == sorted(
                [visible_a.id, visible_b.id]
            )
            assert [item["id"] for item in alice_a["items"]] == [visible_a.id]
            assert [item["id"] for item in alice_b["items"]] == [visible_b.id]
            assert (alice_all["count"], alice_a["count"], alice_b["count"]) == (2, 1, 1)
            visible_read = await case.request("GET", f"/v1/resources/{visible_a.id}", actor="alice")
            assert visible_read.status_code == 200, visible_read.text

            # A project IRI is organizational metadata. Creating a hidden
            # resource with the same IRI must not redact the visible value.
            await case.provision(
                entity_record(PROJECT_A, label="Private project record"), restricted
            )
            assert _observation(await search("alice", PROJECT_A)) == _observation(alice_a)
            after_read = await case.request("GET", f"/v1/resources/{visible_a.id}", actor="alice")
            assert after_read.status_code == 200, after_read.text
            assert after_read.json() == visible_read.json()

            # A protected entity joins the same project view through a normal
            # reviewed content edit; its binding remains in the restricted scope.
            moved = entity_record(hidden.id, label="Restricted member", project=PROJECT_A)
            change = await new_changeset(case, [replace(moved, "Move project reference")])
            assert (await reviewed_apply(case, change["id"]))["state"] == "applied"
            assert await case.fga.bindings(resource_object(hidden.id)) == [scope_object(restricted)]
            assert await case.fga.bindings(resource_object(visible_a.id)) == [scope_object(shared)]

            after_all = await search("alice")
            after_a = await search("alice", PROJECT_A)
            after_b = await search("alice", PROJECT_B)
            assert _observation(after_all) == _observation(alice_all)
            assert _observation(after_a) == _observation(alice_a)
            assert _observation(after_b) == _observation(alice_b)
            assert after_a["revision"] != alice_a["revision"]

            hidden_get = await case.request("GET", f"/v1/entities/{hidden.id}", actor="alice")
            assert hidden_get.status_code == 404, hidden_get.text
            bob_a = await search("bob", PROJECT_A)
            assert hidden.id in {item["id"] for item in bob_a["items"]}
            assert visible_a.id in {item["id"] for item in bob_a["items"]}

    asyncio.run(run())
