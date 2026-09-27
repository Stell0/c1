"""M04-T02: payload edits clear approval and independent review is enforced."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace as dataclass_replace

import httpx
import pytest

from c1.api.app import create_app
from c1.runtime import Runtime
from tests.integration.m04.conftest import (
    action,
    changeset_path,
    create,
    live_case,
    new_changeset,
    new_entity,
    seeded_scope,
)


def test_t02_edit_requires_fresh_review_and_self_review_policy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T02 review")
            first = new_entity("Initial proposal")
            proposed = await new_changeset(case, [create(first, scope)])
            cs_id = proposed["id"]
            await action(case, cs_id, "submit")
            current = await case.request("GET", changeset_path(cs_id), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, cs_id, "validate")
            approved = await action(case, cs_id, "approve", actor="carol")
            old_validation = approved["validation_report_id"]
            old_review = approved["review_decision_id"]
            replacement = new_entity("Edited proposal")
            edited_response = await case.request(
                "PUT",
                changeset_path(cs_id, "operations"),
                actor="bob",
                json={"operations": [create(replacement, scope)]},
            )
            assert edited_response.status_code == 200, edited_response.text
            edited = edited_response.json()
            assert edited["state"] == "draft"
            assert edited["attempt"] == approved["attempt"] + 1
            assert edited["validation_report_id"] is None
            assert edited["review_decision_id"] is None
            old_report = await case.journal.get("ValidationReport", old_validation)
            old_decision = await case.journal.get("ReviewDecision", old_review)
            assert old_report is not None and old_report["superseded"]
            assert old_decision is not None and old_decision["superseded"]
            denied = await case.request(
                "POST",
                changeset_path(cs_id, "apply"),
                actor="carol",
                headers={"Idempotency-Key": uuid.uuid4().hex},
            )
            assert denied.status_code == 409
            await action(case, cs_id, "submit")
            current = await case.request("GET", changeset_path(cs_id), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, cs_id, "validate")
            self_review = await case.request("POST", changeset_path(cs_id, "approve"), actor="bob")
            assert self_review.status_code == 403
            await action(case, cs_id, "approve", actor="carol")
            assert (await action(case, cs_id, "apply", actor="carol"))["state"] == "applied"

        # A second isolated app instance uses the same real stack with the
        # configured self-review switch disabled before creating its proposal.
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T02 self review enabled")
            await case.grant(scope, "bob", "reviewer")
            await case.runtime.close()
            settings = dataclass_replace(case.settings, independent_review=False)
            runtime = Runtime(settings)
            app = create_app(settings, runtime=runtime)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://c1.test", timeout=10
                ) as client:
                    case.runtime = runtime
                    case.client = client
                    record = new_entity("Self reviewed synthetic record")
                    proposal = await new_changeset(case, [create(record, scope)])
                    cs_id = proposal["id"]
                    await action(case, cs_id, "submit")
                    current = await case.request("GET", changeset_path(cs_id), actor="bob")
                    if current.json()["state"] == "submitted":
                        await action(case, cs_id, "validate")
                    assert (await action(case, cs_id, "approve"))["state"] == "approved"
                    assert (await action(case, cs_id, "apply"))["state"] == "applied"
                    bob_id = (await case.principal("bob")).id
                    assert any(
                        '"operation": "changeset_approve"' in record.message
                        and bob_id in record.message
                        for record in caplog.records
                    )

    asyncio.run(run())
