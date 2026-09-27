"""Demonstrate one reviewed ChangeSet on an isolated copy of the pinned stack.

The shared M04 integration harness creates and removes a fresh knowledge
database, workflow database, and OpenFGA store. Only synthetic identifiers,
the commit receipt, and authorized history metadata are printed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, cast

from tests.integration.m04.conftest import (
    action,
    assertion_record,
    create,
    entity_record,
    evidence_record,
    identifier,
    live_case,
    new_changeset,
    seeded_scope,
    source_record,
)


async def demonstrate() -> dict[str, Any]:
    async with live_case() as case:
        scope = await seeded_scope(case, "M04 reviewed write demo")
        subject = entity_record(label="Synthetic demo subject")
        target = entity_record(label="Synthetic demo target")
        await case.provision(subject, scope)
        await case.provision(target, scope)

        source = source_record()
        imported_id = identifier("assertion")
        evidence = evidence_record(imported_id, source.id)
        imported = assertion_record(
            subject.id,
            assertion_id=imported_id,
            object_id=target.id,
            origin="imported",
            evidence_ids=[evidence.id],
            manual_statement=False,
        )
        manual = assertion_record(
            subject.id,
            object_id=target.id,
            attributed_to=(await case.principal("bob")).id,
        )

        instance_response = await case.request("GET", "/v1/instance", actor="bob")
        if instance_response.status_code != 200:
            raise RuntimeError(
                f"Could not read the knowledge head: HTTP {instance_response.status_code}"
            )
        base_revision = instance_response.json()["knowledge_revision"]
        before = await case.knowledge.log()
        proposal = await new_changeset(
            case,
            [
                create(source, scope),
                create(evidence, scope),
                create(imported, scope),
                create(manual, scope),
            ],
            base_revision=base_revision,
        )
        changeset_id = str(proposal["id"])
        submitted = await action(case, changeset_id, "submit")
        if submitted["state"] == "submitted":
            submitted = await action(case, changeset_id, "validate")
        if submitted["state"] != "validated":
            raise RuntimeError("ChangeSet validation did not pass")
        approved = await action(case, changeset_id, "approve", actor="carol")
        if approved["state"] != "approved":
            raise RuntimeError("ChangeSet review did not approve")
        applied = await action(case, changeset_id, "apply", actor="carol")
        if applied["state"] != "applied":
            raise RuntimeError("ChangeSet was not applied")

        after = await case.knowledge.log()
        if len(after) != len(before) + 1:
            raise RuntimeError("Expected exactly one new knowledge commit")
        message = after[0].get("message")
        if not isinstance(message, str):
            raise RuntimeError("Applied commit has no receipt")
        receipt = json.loads(message)
        if not isinstance(receipt, dict) or receipt.get("changeset") != changeset_id:
            raise RuntimeError("Applied commit receipt does not match the ChangeSet")
        if (
            receipt.get("attempt") != 1
            or receipt.get("repository") != case.settings.knowledge_database
            or receipt.get("digest") != applied["approved_digest"]
        ):
            raise RuntimeError("Applied commit receipt does not match the approved attempt")

        response = await case.request(
            "GET",
            "/v1/history",
            actor="alice",
            params={"resource_id": imported.id, "limit": 10},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Authorized history request returned {response.status_code}")
        history = cast(dict[str, Any], response.json())
        if not any(item.get("changeset_id") == changeset_id for item in history["items"]):
            raise RuntimeError("Authorized history omitted the applied ChangeSet")

        return {
            "changeset_id": changeset_id,
            "state": applied["state"],
            "knowledge_commits_added": len(after) - len(before),
            "receipt": receipt,
            "history": history,
        }


def main() -> None:
    # The product audit emits JSON lines; keep stdout machine-readable while
    # retaining the audit stream on stderr for an optional evidence capture.
    audit_logger = logging.getLogger("c1.audit")
    if not audit_logger.handlers:
        audit_logger.addHandler(logging.StreamHandler(sys.stderr))
    print(json.dumps(asyncio.run(demonstrate()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
