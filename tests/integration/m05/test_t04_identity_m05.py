"""M05-T04: reviewed identity changes preserve IDs, bindings, and history."""

from __future__ import annotations

import asyncio
import os
from typing import Any, cast

import pytest

from c1.authorization.fga import resource_object, scope_object
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from tests.integration.m04.conftest import (
    C1,
    RDF,
    LiveCase,
    action,
    assertion_record,
    changeset_path,
    create,
    entity_record,
    live_case,
    new_changeset,
    seeded_scope,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]


async def _reviewed(
    case: LiveCase, change_id: str, author: str = "bob", reviewer: str = "carol"
) -> dict[str, Any]:
    submitted = await action(case, change_id, "submit", actor=author)
    if submitted["state"] == "submitted":
        submitted = await action(case, change_id, "validate", actor=author)
    assert submitted["state"] == "validated"
    await action(case, change_id, "approve", actor=reviewer)
    return await action(case, change_id, "apply", actor=reviewer)


def test_t04_identity_merge_and_undo_keep_current_binding() -> None:
    async def run() -> None:
        async with live_case() as case:

            async def fresh_user_token(name: str) -> str:
                return (await case.token_source.user(name)).access

            # This real-service workflow exceeds the five-minute token lifetime.
            # Refresh tokens for the same principal rather than extending auth
            # lifetime or changing authorization behavior.
            cast(Any, case).token = fresh_user_token
            scope = await seeded_scope(case, "M05-T04 identity")
            for name in ("erin", "frank"):
                principal = await case.principal(name)
                await case.fga.write(
                    [(principal.id, "schema_admin", "instance:" + case.settings.instance_id)]
                )
            install = await new_changeset(
                case, [{"kind": "install_profile", "profile": "identity"}], actor="erin"
            )
            assert (await _reviewed(case, install["id"], "erin", "frank"))["state"] == "applied"
            survivor = entity_record(label="Ada Example")
            merged = entity_record(label="A. Example")
            await case.provision(survivor, scope)
            await case.provision(merged, scope)
            claim = assertion_record(
                merged.id,
                object_id=survivor.id,
                attributed_to=(await case.principal("bob")).id,
            )
            added = await new_changeset(case, [create(claim, scope)])
            assert (await _reviewed(case, added["id"]))["state"] == "applied"

            incomplete = await new_changeset(
                case,
                [
                    {
                        "kind": "merge",
                        "surviving_id": survivor.id,
                        "merged_id": merged.id,
                        "alias_plan": "copy",
                        "assertion_plan": [],
                        "rationale": "same person",
                        "scope_id": scope,
                    }
                ],
            )
            assert (await action(case, incomplete["id"], "submit"))["state"] == "rejected"
            report = await case.request(
                "GET", changeset_path(incomplete["id"], "validation"), actor="bob"
            )
            assert report.status_code == 200, report.text
            assert "C1-CS-040" in {item["code"] for item in report.json()["diagnostics"]}

            merge = await new_changeset(
                case,
                [
                    {
                        "kind": "merge",
                        "surviving_id": survivor.id,
                        "merged_id": merged.id,
                        "alias_plan": "copy",
                        "assertion_plan": [{"assertion_id": claim.id, "action": "move"}],
                        "rationale": "same person",
                        "scope_id": scope,
                    }
                ],
            )
            submitted = await action(case, merge["id"], "submit")
            assert submitted["state"] == "validated"
            validation = await case.request(
                "GET", changeset_path(merge["id"], "validation"), actor="bob"
            )
            assert validation.status_code == 200, validation.text
            expanded = validation.json()["expanded_operations"]
            assert len(expanded) == 5
            assert all(item["kind"] in {"create", "replace"} for item in expanded)
            assert submitted["request_digest"] == validation.json()["request_digest"]
            await action(case, merge["id"], "approve", actor="carol")
            assert (await action(case, merge["id"], "apply", actor="carol"))["state"] == "applied"
            changed_claim = await case.knowledge.get_record(claim.id, case.runtime.registry)
            assert changed_claim is not None
            assert changed_claim.properties[RDF + "subject"] == [survivor.id]
            changed_merged = await case.knowledge.get_record(merged.id, case.runtime.registry)
            assert changed_merged is not None
            lifecycle = changed_merged.properties[C1 + "lifecycle"][0]
            assert isinstance(lifecycle, LiteralValue) and lifecycle.lexical == "superseded"
            merged_survivor = await case.knowledge.get_record(survivor.id, case.runtime.registry)
            assert merged_survivor is not None
            copied_label = merged.properties["http://www.w3.org/2004/02/skos/core#prefLabel"][0]
            assert isinstance(copied_label, LiteralValue)
            assert merged_survivor.properties.get(
                "http://www.w3.org/2004/02/skos/core#altLabel", []
            ) == [copied_label]
            assert await case.fga.bindings(resource_object(claim.id)) == [scope_object(scope)]
            redirect_op = next(
                item
                for item in expanded
                if item["kind"] == "create"
                and "urn:c1:ns:identity#Redirect" in item["record"]["types"]
            )
            redirect = NodeRecord.model_validate(redirect_op["record"])
            assert redirect.properties["urn:c1:ns:identity#copiedAlias"] == [copied_label]
            assert await case.fga.bindings(resource_object(redirect.id)) == [scope_object(scope)]
            resolution_op = next(
                item
                for item in expanded
                if item["kind"] == "create" and C1 + "ResolutionRecord" in item["record"]["types"]
            )
            resolution = NodeRecord.model_validate(resolution_op["record"])
            undo = await new_changeset(
                case,
                [
                    {
                        "kind": "undo_merge",
                        "resolution_id": resolution.id,
                        "reassignment_plan": [{"assertion_id": claim.id, "action": "move"}],
                        "rationale": "mistaken match",
                        "scope_id": scope,
                    }
                ],
            )
            assert (await _reviewed(case, undo["id"]))["state"] == "applied"
            restored_claim = await case.knowledge.get_record(claim.id, case.runtime.registry)
            assert restored_claim is not None
            assert restored_claim.properties[RDF + "subject"] == [merged.id]
            restored_redirect = await case.knowledge.get_record(redirect.id, case.runtime.registry)
            assert restored_redirect is not None
            lifecycle = restored_redirect.properties[C1 + "lifecycle"][0]
            assert isinstance(lifecycle, LiteralValue) and lifecycle.lexical == "retracted"
            restored_survivor = await case.knowledge.get_record(survivor.id, case.runtime.registry)
            assert restored_survivor is not None
            assert not restored_survivor.properties.get(
                "http://www.w3.org/2004/02/skos/core#altLabel", []
            )
            assert await case.fga.bindings(resource_object(claim.id)) == [scope_object(scope)]

    asyncio.run(run())
