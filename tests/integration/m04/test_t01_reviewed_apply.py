"""M04-T01: reviewed assertions publish in one attributable commit."""

from __future__ import annotations

import asyncio
import json

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m04.conftest import (
    C1,
    action,
    assertion_record,
    create,
    entity_record,
    evidence_record,
    identifier,
    live_case,
    new_changeset,
    path,
    seeded_scope,
    source_record,
)


def test_t01_reviewed_source_and_manual_claims_commit_once() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T01 claims")
            subject = entity_record(label="Synthetic subject")
            target = entity_record(label="Synthetic target")
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
            assert C1 + "evidence" not in manual.properties
            before = await case.knowledge.log()
            proposal = await new_changeset(
                case,
                [
                    create(source, scope),
                    create(evidence, scope),
                    create(imported, scope),
                    create(manual, scope),
                ],
            )
            changeset_id = proposal["id"]
            submitted = await action(case, changeset_id, "submit")
            if submitted["state"] == "submitted":
                submitted = await action(case, changeset_id, "validate")
            assert submitted["state"] == "validated"
            validation = await case.request(
                "GET", f"/v1/changesets/{changeset_id}/validation", actor="bob"
            )
            assert validation.status_code == 200, validation.text
            assert not [d for d in validation.json()["diagnostics"] if d["severity"] == "error"]
            assert (await action(case, changeset_id, "approve", actor="carol"))[
                "state"
            ] == "approved"
            applied = await action(case, changeset_id, "apply", actor="carol")
            assert applied["state"] == "applied"
            after = await case.knowledge.log()
            assert len(after) == len(before) + 1
            receipt = json.loads(after[0]["message"])
            assert receipt["changeset"] == changeset_id
            assert receipt["attempt"] == 1
            assert receipt["repository"] == case.settings.knowledge_database
            assert receipt["digest"] == applied["approved_digest"]
            for record in (source, evidence, imported, manual):
                assert await case.fga.bindings(resource_object(record.id)) == [scope_object(scope)]
                binding = await case.journal.get("Binding", record.id)
                assert binding is not None and binding["state"] == "active"
                read = await case.request("GET", path(record.id), actor="alice")
                assert read.status_code == 200, read.text
                assert read.json() == record.model_dump(mode="json")
            records = await case.knowledge.read_records(case.runtime.registry)
            activities = [
                record
                for record in records
                if "http://www.w3.org/ns/prov#Activity" in record.types
                and any(
                    getattr(value, "lexical", None) == "changeset-apply"
                    for value in record.properties.get(C1 + "method", [])
                )
            ]
            assert len(activities) == 1
            assert await case.fga.bindings(resource_object(activities[0].id)) == [
                scope_object(scope)
            ]
            assert await case.journal.list("ApplyReceipt")

            invalid = assertion_record(
                subject.id,
                object_id=target.id,
                origin="imported",
                manual_statement=False,
            )
            bad = await new_changeset(case, [create(invalid, scope)])
            rejected = await action(case, bad["id"], "submit")
            if rejected["state"] == "submitted":
                rejected = await action(case, bad["id"], "validate")
            assert rejected["state"] == "rejected"
            report = await case.request(
                "GET", f"/v1/changesets/{bad['id']}/validation", actor="bob"
            )
            assert report.status_code == 200
            assert "C1-CS-011" in {d["code"] for d in report.json()["diagnostics"]}
            assert len(await case.knowledge.log()) == len(after)

    asyncio.run(run())
