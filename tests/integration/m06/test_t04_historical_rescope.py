"""M06-T04: present bindings govern document parts at every old revision."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import quote

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m03.conftest import live_case
from tests.integration.m06.conftest import (
    _apply_as_service,
    _service_token,
    install_scoped_document,
)

P2 = "urn:c1:instance:dev:document-part/00000072-0000-4000-8000-000000000000"


def test_t04_rescoped_part_disappears_from_old_document_views() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, scopes, revision1, revision2 = await install_scoped_document(case)
            await case.grant(scopes["doc-public"], "frank", "access_admin")
            await case.grant(scopes["doc-legal"], "frank", "access_admin")
            proposed = await case.request(
                "POST",
                f"/v1/access-scopes/{quote(scopes['doc-legal'], safe='')}/bindings",
                actor="erin",
                json={"resource_id": P2},
            )
            assert proposed.status_code == 200, proposed.text
            operation_id = proposed.json()["id"]
            approved = await case.request(
                "POST",
                f"/v1/security-operations/{quote(operation_id, safe='')}/approve",
                actor="frank",
            )
            assert approved.status_code == 200, approved.text
            applied = await case.request(
                "POST",
                f"/v1/security-operations/{quote(operation_id, safe='')}/apply",
                actor="erin",
            )
            assert applied.status_code == 200, applied.text
            document_path = "/v1/documents/" + quote(fixture["document_id"], safe="")

            for revision in (revision1, revision2):
                public = await case.request(
                    "GET", document_path, actor="alice", params={"revision": revision}
                )
                assert public.status_code == 200, public.text
                assert P2 not in public.text
                assert "The public edition" not in public.text
                historical = await case.request(
                    "GET",
                    document_path + "/render",
                    actor="alice",
                    params={"revision": revision, "format": "markdown"},
                )
                assert historical.status_code == 200, historical.text
                assert "The public edition" not in historical.text
                parts = await case.request(
                    "GET",
                    document_path + "/parts",
                    actor="alice",
                    params={"revision": revision},
                )
                assert parts.status_code == 200, parts.text
                assert P2 not in parts.text
                export = await case.request(
                    "GET",
                    document_path + "/export",
                    actor="alice",
                    params={"revision": revision, "format": "jsonld"},
                )
                assert export.status_code == 200, export.text
                assert P2 not in export.text

            history = await case.request(
                "GET", document_path + "/history", actor="alice", params={"limit": 100}
            )
            assert history.status_code == 200, history.text
            assert P2 not in history.text
            assert "The public edition" not in history.text

            carol = await case.request(
                "GET", document_path, actor="carol", params={"revision": revision1}
            )
            assert carol.status_code == 200, carol.text
            assert P2 in carol.text
            assert "The public edition is current" in carol.text
            carol_parts = await case.request(
                "GET",
                document_path + "/parts",
                actor="carol",
                params={"revision": revision1},
            )
            assert carol_parts.status_code == 200, carol_parts.text
            assert P2 in carol_parts.text

            # Restoring the text is an ordinary knowledge write. It cannot
            # undo the separate current binding move into the legal scope.
            p2 = next(item for item in fixture["revision1"] if item["id"] == P2)
            restored = {
                "id": p2["id"],
                "types": p2["types"],
                "properties": {
                    **p2["properties"],
                    "urn:c1:ns:core#text": [
                        {
                            "lexical": "The text was restored after a scoped review.",
                            "datatype": "http://www.w3.org/2001/XMLSchema#string",
                        }
                    ],
                },
            }
            token = await _service_token(case)
            await _apply_as_service(
                case,
                token,
                [
                    {
                        "kind": "replace",
                        "resource_id": P2,
                        "record": restored,
                        "reason": "Restore the text after re-scope",
                    }
                ],
                "Restore text without changing its AccessScope",
            )
            assert await case.fga.bindings(resource_object(P2)) == [
                scope_object(scopes["doc-legal"])
            ]
            current_alice = await case.request(
                "GET",
                document_path,
                actor="alice",
                params={"revision": await case.knowledge.head()},
            )
            assert current_alice.status_code == 200, current_alice.text
            assert P2 not in current_alice.text
            assert "restored after a scoped review" not in current_alice.text

            # A part's move-out remains part of Handbook history, while edits
            # made after it belongs to Notes do not appear there.
            p3_id = "urn:c1:instance:dev:document-part/00000073-0000-4000-8000-000000000000"
            p3 = next(item for item in fixture["revision1"] if item["id"] == p3_id)
            move_record = {
                "id": p3["id"],
                "types": p3["types"],
                "properties": {
                    **p3["properties"],
                    "urn:c1:ns:core#partOfDocument": [fixture["notes_id"]],
                },
            }
            await _apply_as_service(
                case,
                token,
                [
                    {
                        "kind": "replace",
                        "resource_id": p3["id"],
                        "record": move_record,
                        "reason": "Move a readable part to Notes",
                    }
                ],
                "Move a part out of Handbook",
            )
            move_revision = await case.knowledge.head()
            cursor_page = await case.request(
                "GET", document_path + "/history", actor="carol", params={"limit": 1}
            )
            assert cursor_page.status_code == 200, cursor_page.text
            cursor = cursor_page.json()["next_cursor"]
            assert cursor

            moved_record = {
                **move_record,
                "properties": {
                    **move_record["properties"],
                    "urn:c1:ns:core#text": [
                        {
                            "lexical": "Edited after moving to Notes.",
                            "datatype": "http://www.w3.org/2001/XMLSchema#string",
                        }
                    ],
                },
            }
            await _apply_as_service(
                case,
                token,
                [
                    {
                        "kind": "replace",
                        "resource_id": p3["id"],
                        "record": moved_record,
                        "reason": "Edit the part after it moved",
                    }
                ],
                "Edit the part after it moved to Notes",
            )
            later_revision = await case.knowledge.head()
            stale = await case.request(
                "GET",
                document_path + "/history",
                actor="carol",
                params={"limit": 1, "cursor": cursor},
            )
            assert stale.status_code == 409, stale.text
            assert stale.json().get("code") == "C1-DC-014"
            history = await case.request(
                "GET", document_path + "/history", actor="carol", params={"limit": 100}
            )
            assert history.status_code == 200, history.text
            revisions = {item["revision"] for item in history.json()["items"]}
            assert move_revision in revisions
            assert later_revision not in revisions

            # Revoke Alice's real scope grant after the route has fetched its
            # history snapshot but immediately before final authorization.
            # The guard must reject the whole response and never publish the
            # stale history page.
            alice_id = (await case.principal("alice")).id
            public_reader = (alice_id, "reader", scope_object(scopes["doc-public"]))
            planner = case.runtime.query.planner
            original_finalize_after = planner.finalize_after
            injected = False
            revoked = False

            async def revoke_before_finalize(
                principal: Any,
                plan: Any,
                precondition: Callable[[], Awaitable[None]],
                *,
                deadline: float | None = None,
            ) -> None:
                nonlocal injected, revoked
                await case.fga.write([], deletes=[public_reader])
                revoked = True
                assert not await case.fga.check(
                    alice_id, "reader", scope_object(scopes["doc-public"])
                )
                injected = True
                await original_finalize_after(principal, plan, precondition, deadline=deadline)

            cast(Any, planner).finalize_after = revoke_before_finalize
            try:
                revoked_history = await case.request(
                    "GET", document_path + "/history", actor="alice", params={"limit": 100}
                )
            finally:
                cast(Any, planner).finalize_after = original_finalize_after
                if revoked:
                    await case.fga.write([public_reader])
            assert injected, "the late authorization revocation hook did not run"
            assert revoked_history.status_code in {409, 503}, revoked_history.text
            assert revoked_history.json().get("items", []) == []

    asyncio.run(run())
