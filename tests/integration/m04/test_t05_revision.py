"""M04-T05: workflow bookkeeping is separate from knowledge revision checks."""

from __future__ import annotations

import asyncio

from tests.integration.m03.conftest import LiveCase
from tests.integration.m04.conftest import (
    action,
    changeset_path,
    create,
    live_case,
    new_changeset,
    new_entity,
    seeded_scope,
)


async def _approve(case: LiveCase, changeset_id: str) -> None:
    await action(case, changeset_id, "submit")
    current = await case.request("GET", changeset_path(changeset_id), actor="bob")
    if current.json()["state"] == "submitted":
        await action(case, changeset_id, "validate")
    await action(case, changeset_id, "approve", actor="carol")


def test_t05_workflow_writes_do_not_stale_but_knowledge_writes_do() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T05 revision")
            head = await case.knowledge.head()
            a = await new_changeset(case, [create(new_entity("A"), scope)], base_revision=head)
            for index in range(10):
                extra = await new_changeset(
                    case,
                    [create(new_entity(f"Workflow only {index}"), scope)],
                    base_revision=head,
                )
                await _approve(case, extra["id"])
            assert await case.knowledge.head() == head
            await _approve(case, a["id"])
            assert (await action(case, a["id"], "apply", actor="carol"))["state"] == "applied"
            next_head = await case.knowledge.head()
            assert next_head != head

            b = await new_changeset(case, [create(new_entity("B"), scope)], base_revision=next_head)
            c_record = new_entity("C")
            c = await new_changeset(case, [create(c_record, scope)], base_revision=next_head)
            await _approve(case, b["id"])
            await _approve(case, c["id"])
            assert (await action(case, b["id"], "apply", actor="carol"))["state"] == "applied"
            after_b = await case.knowledge.head()
            assert after_b != next_head
            stale = await case.request(
                "POST",
                changeset_path(c["id"], "apply"),
                actor="carol",
                headers={"Idempotency-Key": "m04-t05-stale"},
            )
            assert stale.status_code == 409, stale.text
            assert (await case.request("GET", changeset_path(c["id"]), actor="bob")).json()[
                "state"
            ] == "stale"
            assert await case.knowledge.head() == after_b
            rebased = await case.request(
                "POST",
                changeset_path(c["id"], "rebase"),
                actor="bob",
                json={"base_revision": after_b},
            )
            assert rebased.status_code == 200, rebased.text
            assert rebased.json()["state"] == "submitted"
            assert rebased.json()["validation_report_id"] is None
            await action(case, c["id"], "validate")
            await action(case, c["id"], "approve", actor="carol")
            assert (await action(case, c["id"], "apply", actor="carol"))["state"] == "applied"
            assert await case.knowledge.head() != after_b

    asyncio.run(run())
