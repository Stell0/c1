"""M03-T05: binding anomalies and inherited parts fail closed."""

from __future__ import annotations

import asyncio
import uuid

from c1.authorization.fga import resource_object, scope_object
from c1.authorization.models import Binding
from c1.interchange import validate_records
from c1.model.profiles import ProfileRegistry
from tests.integration.m03.conftest import (
    document_record,
    entity_record,
    live_case,
    part_record,
    resource_path,
)


def test_t05_missing_ambiguous_unknown_and_inactive_bindings() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await case.scope("M03-T05 owned")
            other = await case.scope("M03-T05 other")
            await case.grant(scope, "alice", "reader")
            record = entity_record(label="Binding anomalies")
            await case.provision(record, scope)
            path = resource_path(record.id)
            obj = resource_object(record.id)
            original = (scope_object(scope), "bound_to", obj)
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            await case.fga.write([], deletes=[original])
            assert (await case.request("GET", path, actor="alice")).status_code == 404
            await case.fga.write([original])
            extra = (scope_object(other), "bound_to", obj)
            await case.fga.write([extra])
            assert (await case.request("GET", path, actor="alice")).status_code == 404
            await case.fga.write([], deletes=[extra])

            unknown = ("scope:never_created", "bound_to", obj)
            await case.fga.write([unknown], deletes=[original])
            assert (await case.request("GET", path, actor="alice")).status_code == 404
            await case.fga.write([original], deletes=[unknown])

            value = await case.journal.get("Binding", record.id)
            assert value is not None
            binding = Binding.model_validate(value)
            for state in ("transitioning", "revoked"):
                binding.state = state
                await case.journal.save_many(
                    [("Binding", record.id, binding.model_dump(mode="json"))]
                )
                assert (await case.request("GET", path, actor="alice")).status_code == 404
            binding.state = "active"
            await case.journal.save_many([("Binding", record.id, binding.model_dump(mode="json"))])
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            # A knowledge record without any security journal entry is invisible.
            orphan = entity_record("urn:c1:probe:orphan-" + uuid.uuid4().hex)
            await case.knowledge.write_records(
                validate_records([orphan], ProfileRegistry()),
                ProfileRegistry(),
                expected_head=await case.knowledge.head(),
            )
            assert (
                await case.request("GET", resource_path(orphan.id), actor="alice")
            ).status_code == 404

            refused = await case.request("DELETE", f"/v1/access-scopes/{scope}")
            assert refused.status_code == 409, refused.text
            assert await case.fga.bindings(obj) == [scope_object(scope)]
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            # The scope with no journal dependent still cannot retire while an
            # orphan native tuple points at it; after removal, retirement works.
            orphan_tuple = (
                scope_object(other),
                "bound_to",
                resource_object("urn:c1:probe:orphan-tuple-" + uuid.uuid4().hex),
            )
            await case.fga.write([orphan_tuple])
            refused_orphan = await case.request("DELETE", f"/v1/access-scopes/{other}")
            assert refused_orphan.status_code == 409, refused_orphan.text
            await case.fga.write([], deletes=[orphan_tuple])
            retired = await case.request("DELETE", f"/v1/access-scopes/{other}")
            assert retired.status_code == 200, retired.text
            assert retired.json()["state"] == "applied"
            retired_scope = await case.journal.get("Scope", other)
            assert retired_scope is not None and retired_scope["state"] == "retired"

    asyncio.run(run())


def test_t05_document_part_inheritance_cascades_with_current_policy() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await case.scope("M03-T05 document")
            private = await case.scope("M03-T05 private")
            await case.grant(shared, "alice", "reader")
            await case.grant(private, "frank", "access_admin")
            document = document_record()
            part = part_record(document.id)
            await case.provision(document, shared)
            child = await case.request(
                "POST",
                "/v1/probe/resources",
                json={"record": part.model_dump(mode="json"), "inherited_from": document.id},
            )
            assert child.status_code == 201, child.text
            child_binding = await case.journal.get("Binding", part.id)
            assert child_binding is not None
            assert child_binding["inherited_from"] == document.id
            assert child_binding["scope_id"] == shared
            for resource in (document, part):
                assert (
                    await case.request("GET", resource_path(resource.id), actor="alice")
                ).status_code == 200

            proposed = await case.request(
                "POST",
                f"/v1/access-scopes/{private}/bindings",
                json={"resource_id": document.id},
            )
            assert proposed.status_code == 200, proposed.text
            op = proposed.json()
            assert set(op["targets"]) == {document.id, part.id}
            approved = await case.request(
                "POST", f"/v1/security-operations/{op['id']}/approve", actor="frank"
            )
            assert approved.status_code == 200, approved.text
            applied = await case.request("POST", f"/v1/security-operations/{op['id']}/apply")
            assert applied.status_code == 200, applied.text
            for resource in (document, part):
                assert await case.fga.bindings(resource_object(resource.id)) == [
                    scope_object(private)
                ]
                assert (
                    await case.request("GET", resource_path(resource.id), actor="alice")
                ).status_code == 404
                assert (await case.request("GET", resource_path(resource.id))).status_code == 200

    asyncio.run(run())
