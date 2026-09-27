"""M03-T03: endpoint and project visibility never grants a protected relation."""

from __future__ import annotations

import asyncio
import uuid

from tests.integration.m03.conftest import (
    entity_record,
    evidence_record,
    live_case,
    relation_record,
    resource_path,
    source_record,
)


def test_t03_relation_evidence_source_and_project_grants_are_independent() -> None:
    async def run() -> None:
        async with live_case() as case:
            visible_scope = await case.scope("M03-T03 visible")
            hidden_scope = await case.scope("M03-T03 hidden")
            await case.grant(visible_scope, "alice", "reader")
            project = "urn:c1:project:synthetic-" + uuid.uuid4().hex
            a = entity_record(label="A", project=project)
            b = entity_record(label="B", project=project)
            await case.provision(a, visible_scope)
            await case.provision(b, visible_scope)

            erin = await case.principal("erin")
            relation = relation_record(a.id, b.id, erin.id)
            source = source_record()
            evidence = evidence_record(relation.id, source.id)
            await case.provision(relation, hidden_scope)
            await case.provision(source, hidden_scope)
            await case.provision(evidence, hidden_scope)

            for entity in (a, b):
                assert (
                    await case.request("GET", resource_path(entity.id), actor="alice")
                ).status_code == 200
            hidden = await case.request("GET", resource_path(relation.id), actor="alice")
            assert hidden.status_code == 404
            assert (
                await case.request("GET", resource_path(evidence.id), actor="alice")
            ).status_code == 404
            assert (
                await case.request("GET", resource_path(source.id), actor="alice")
            ).status_code == 404
            missing = await case.request(
                "GET", resource_path("urn:c1:probe:missing-" + uuid.uuid4().hex), actor="alice"
            )
            assert missing.status_code == 404
            assert hidden.json() == missing.json()

            # This group has no scope role. A project edge is knowledge, not a grant.
            alice = await case.principal("alice")
            group = "group:project_" + uuid.uuid4().hex
            await case.fga.write([(alice.id, "member", group)])
            assert (
                await case.request("GET", resource_path(relation.id), actor="alice")
            ).status_code == 404
            assert (
                await case.request("GET", resource_path(evidence.id), actor="alice")
            ).status_code == 404

    asyncio.run(run())
