"""M05-T05: revision-pinned cursors reauthorize every continuation."""

from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import quote

import pytest

from c1.query.filters import QueryFilters, filter_digest
from tests.integration.m04.conftest import (
    C1,
    assertion_record,
    create,
    entity_record,
    identifier,
    live_case,
    new_changeset,
    reviewed_apply,
    seeded_scope,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]

_BASE = "urn:c1:probe:entity-m05-t05-"


def test_t05_entity_cursor_pins_revision_and_rechecks_current_access() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M05-T05 shared")
            restricted = await case.scope("M05-T05 restricted")
            await case.grant(restricted, "alice", "reader")
            await case.grant(shared, "alice", "reader")
            await case.grant(shared, "bob", "reader")
            for suffix, scope in (
                ("020", shared),
                ("040", shared),
                ("060", restricted),
                ("080", restricted),
            ):
                await case.provision(entity_record(_BASE + suffix, label=suffix), scope)

            first = await case.request("GET", "/v1/entities", actor="alice", params={"limit": 2})
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert [item["id"] for item in first_body["items"]] == [_BASE + "020", _BASE + "040"]
            assert first_body["count"] == 4
            cursor = first_body["next_cursor"]
            assert isinstance(cursor, str) and cursor
            pinned_revision = first_body["revision"]

            # A new record would sort into the first page at the current head.
            inserted = entity_record(identifier("entity"), label="inserted later")
            change = await new_changeset(case, [create(inserted, shared)])
            assert (await reviewed_apply(case, change["id"]))["state"] == "applied"
            current = await case.request("GET", "/v1/entities", actor="alice", params={"limit": 2})
            assert current.status_code == 200, current.text
            assert [item["id"] for item in current.json()["items"]] == [
                inserted.id,
                _BASE + "020",
            ]
            second = await case.request(
                "GET", "/v1/entities", actor="alice", params={"limit": 2, "cursor": cursor}
            )
            assert second.status_code == 200, second.text
            assert second.json()["revision"] == pinned_revision
            assert [item["id"] for item in second.json()["items"]] == [
                _BASE + "060",
                _BASE + "080",
            ]
            repeated = await case.request(
                "GET", "/v1/entities", actor="alice", params={"limit": 2, "cursor": cursor}
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["items"] == second.json()["items"]

            alice = await case.principal("alice")
            revoked = await case.request(
                "DELETE",
                f"/v1/access-scopes/{restricted}/members/{quote(alice.id, safe='')}?role=reader",
            )
            assert revoked.status_code == 200, revoked.text
            after_revoke = await case.request(
                "GET", "/v1/entities", actor="alice", params={"limit": 2, "cursor": cursor}
            )
            assert after_revoke.status_code == 200, after_revoke.text
            assert after_revoke.json()["revision"] == pinned_revision
            assert after_revoke.json()["items"] == []
            assert after_revoke.json()["count"] == 2
            for suffix in ("060", "080"):
                hidden = await case.request(
                    "GET", "/v1/entities/" + quote(_BASE + suffix, safe=""), actor="alice"
                )
                assert hidden.status_code == 404

            tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
            for token, actor in ((tampered, "alice"), (cursor, "bob")):
                invalid = await case.request(
                    "GET", "/v1/entities", actor=actor, params={"limit": 2, "cursor": token}
                )
                assert invalid.status_code == 400, invalid.text
                assert invalid.json()["code"] == "C1-QY-004"

            position = case.runtime.query.codec.decode(
                cursor,
                principal=alice.id,
                filter_digest=filter_digest(QueryFilters(limit=2)),
                order="id",
            )
            expired = case.runtime.query.codec.encode(
                principal=alice.id,
                revision=position.revision,
                filter_digest=position.filter_digest,
                order=position.order,
                last_key=position.last_key,
                now=int(time.time()) - 901,
            )
            invalid = await case.request(
                "GET", "/v1/entities", actor="alice", params={"limit": 2, "cursor": expired}
            )
            assert invalid.status_code == 400, invalid.text
            assert invalid.json()["code"] == "C1-QY-004"

    asyncio.run(run())


def test_t05_traversal_cursor_restarts_after_frontier_rescope() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await seeded_scope(case, "M05-T05 traversal")
            private = await case.scope("M05-T05 traversal private")
            await case.grant(private, "frank", "access_admin")
            a, b, c = [entity_record(_BASE + suffix) for suffix in ("a", "b", "c")]
            for record in (a, b, c):
                await case.provision(record, shared)
            principal = await case.principal("bob")
            edges = [
                assertion_record(a.id, object_id=b.id, attributed_to=principal.id),
                assertion_record(b.id, object_id=c.id, attributed_to=principal.id),
            ]
            change = await new_changeset(case, [create(edge, shared) for edge in edges])
            assert (await reviewed_apply(case, change["id"]))["state"] == "applied"

            path = "/v1/entities/" + quote(a.id, safe="") + "/neighborhood"
            params = {"predicates": C1 + "worksFor", "depth": 2, "limit": 1}
            first = await case.request("GET", path, actor="alice", params=params)
            assert first.status_code == 200, first.text
            cursor = first.json()["next_cursor"]
            assert isinstance(cursor, str) and cursor, first.text
            normal_continuation = await case.request(
                "GET", path, actor="alice", params={**params, "cursor": cursor}
            )
            assert normal_continuation.status_code == 200, normal_continuation.text
            assert [edge["assertion_id"] for edge in normal_continuation.json()["edges"]] == [
                edges[1].id
            ]
            assert [node["id"] for node in normal_continuation.json()["nodes"]] == [c.id]

            proposed = await case.request(
                "POST", f"/v1/access-scopes/{private}/bindings", json={"resource_id": b.id}
            )
            assert proposed.status_code == 200, proposed.text
            operation = proposed.json()
            assert (
                await case.request(
                    "POST", f"/v1/security-operations/{operation['id']}/approve", actor="frank"
                )
            ).status_code == 200
            applied = await case.request("POST", f"/v1/security-operations/{operation['id']}/apply")
            assert applied.status_code == 200, applied.text
            continued = await case.request(
                "GET", path, actor="alice", params={**params, "cursor": cursor}
            )
            assert continued.status_code == 409, continued.text
            assert continued.json()["code"] == "C1-QY-051"

    asyncio.run(run())
