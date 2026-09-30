"""M04-T07: unresolved references, schema authority, and preserved conflicts."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import pytest

from c1.api.app import create_app
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import AssertionRecord, EvidenceRecord, SourceRecord
from c1.runtime import Runtime
from scripts import api as api_process
from tests.integration.m03.conftest import LiveCase, bearer, client_timeout
from tests.integration.m03.conftest import source_record as probe_source_record
from tests.integration.m04.conftest import (
    C1,
    XSD,
    action,
    assertion_record,
    changeset_path,
    create,
    entity_record,
    identifier,
    live_case,
    new_changeset,
    path,
    seeded_scope,
    string,
)
from tests.integration.m04.test_t04_retry_crash import _api_up

VEHICLE = "urn:c1:ns:example-vehicle#"
TIME = "http://www.w3.org/2006/time#"


def _probe_id(kind: str) -> str:
    return f"urn:c1:probe:{kind}-{uuid.uuid4().hex}"


async def _validated(case: LiveCase, changeset_id: str, actor: str = "bob") -> dict[str, Any]:
    result = await action(case, changeset_id, "submit", actor=actor)
    if result["state"] == "submitted":
        result = await action(case, changeset_id, "validate", actor=actor)
    return result


def test_t07_absent_and_hidden_references_are_equally_unresolved() -> None:
    async def run() -> None:
        async with live_case() as case:
            visible = await seeded_scope(case, "M04-T07 visible")
            hidden = await case.scope("M04-T07 hidden")
            subject = entity_record(label="Referenced subject")
            target = entity_record(label="Referenced target")
            await case.provision(subject, visible)
            await case.provision(target, visible)
            before = await case.knowledge.head()
            missing = assertion_record(
                subject.id,
                object_id=target.id,
                origin="imported",
                evidence_ids=[identifier("evidence")],
                manual_statement=False,
            )
            proposal = await new_changeset(case, [create(missing, visible)])
            assert (await _validated(case, proposal["id"]))["state"] == "rejected"
            missing_report = await case.request(
                "GET", changeset_path(proposal["id"], "validation"), actor="bob"
            )
            assert missing_report.status_code == 200
            assert "C1-CS-010" in {d["code"] for d in missing_report.json()["diagnostics"]}

            source = probe_source_record()
            await case.provision(source, hidden)
            hidden_claim = assertion_record(
                subject.id,
                object_id=target.id,
                origin="imported",
                evidence_ids=[source.id],
                manual_statement=False,
            )
            hidden_proposal = await new_changeset(case, [create(hidden_claim, visible)])
            assert (await _validated(case, hidden_proposal["id"]))["state"] == "rejected"
            hidden_report = await case.request(
                "GET", changeset_path(hidden_proposal["id"], "validation"), actor="bob"
            )
            assert hidden_report.status_code == 200
            assert "C1-CS-010" in {d["code"] for d in hidden_report.json()["diagnostics"]}
            assert await case.knowledge.head() != before  # only hidden fixture provision changed it
            assert (await case.request("GET", path(missing.id), actor="alice")).status_code == 404
            assert (
                await case.request("GET", path(hidden_claim.id), actor="alice")
            ).status_code == 404

    asyncio.run(run())


def test_t07_schema_install_and_competing_single_valued_claims() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T07 schema and conflict")
            denied = await new_changeset(
                case, [{"kind": "install_profile", "profile": "example-vehicle"}], actor="dave"
            )
            rejected = await case.request(
                "POST", changeset_path(denied["id"], "submit"), actor="dave"
            )
            assert rejected.status_code == 403, rejected.text

            for name in ("erin", "frank"):
                principal = await case.principal(name)
                await case.fga.write(
                    [(principal.id, "schema_admin", "instance:" + case.settings.instance_id)]
                )
            schema_before = await case.knowledge.schema_documents()
            install = await new_changeset(
                case, [{"kind": "install_profile", "profile": "example-vehicle"}], actor="erin"
            )
            assert (await _validated(case, install["id"], actor="erin"))["state"] == "validated"
            await action(case, install["id"], "approve", actor="frank")
            assert (await action(case, install["id"], "apply", actor="frank"))["state"] == "applied"
            assert await case.knowledge.schema_documents() != schema_before

            vehicle = NodeRecord(
                id=identifier("entity"),
                types=[VEHICLE + "Vehicle"],
                properties={
                    "http://www.w3.org/2004/02/skos/core#prefLabel": [
                        LiteralValue(
                            lexical="Synthetic vehicle",
                            datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                            language="en",
                        )
                    ],
                    C1 + "lifecycle": [string("active")],
                    VEHICLE + "wheelCount": [LiteralValue(lexical="4", datatype=XSD + "integer")],
                },
            )
            content = await new_changeset(case, [create(vehicle, scope)])
            assert (await _validated(case, content["id"]))["state"] == "validated"
            await action(case, content["id"], "approve", actor="carol")
            assert (await action(case, content["id"], "apply", actor="carol"))["state"] == "applied"
            assert (await case.request("GET", path(vehicle.id), actor="alice")).status_code == 200

            # The registered incompatible revision is a migration proposal,
            # not an in-place schema change.
            prior = await case.knowledge.schema_documents()
            incompatible = await new_changeset(
                case,
                [{"kind": "install_profile", "profile": "example-vehicle-v2-incompatible"}],
                actor="erin",
            )
            assert (await _validated(case, incompatible["id"], actor="erin"))["state"] == "rejected"
            report = await case.request(
                "GET", changeset_path(incompatible["id"], "validation"), actor="erin"
            )
            assert "C1-PR-004" in {d["code"] for d in report.json()["diagnostics"]}
            assert await case.journal.list("MigrationProposal")
            assert await case.knowledge.schema_documents() == prior

            begin = NodeRecord(
                id=_probe_id("boundary"),
                types=[C1 + "TimeBoundary"],
                properties={
                    C1 + "boundaryState": [string("known")],
                    TIME + "inXSDDate": [
                        LiteralValue(lexical="2020-01-01Z", datatype=XSD + "date")
                    ],
                },
            )
            end = NodeRecord(
                id=_probe_id("boundary"),
                types=[C1 + "TimeBoundary"],
                properties={
                    C1 + "boundaryState": [string("known")],
                    TIME + "inXSDDate": [
                        LiteralValue(lexical="2021-01-01Z", datatype=XSD + "date")
                    ],
                },
            )
            interval = NodeRecord(
                id=_probe_id("interval"),
                types=[C1 + "TimeInterval"],
                properties={TIME + "hasBeginning": [begin.id], TIME + "hasEnd": [end.id]},
            )
            for record in (begin, end, interval):
                await case.provision(record, scope)
            claims: list[NodeRecord] = []
            sources: list[NodeRecord] = []
            evidence: list[NodeRecord] = []
            for count, source_name in ((4, "A"), (5, "B")):
                revision = f"conflict-source-{source_name.lower()}"
                source = SourceRecord(
                    id=identifier("source"),
                    title=string(f"Synthetic measurement source {source_name}"),
                    kind="document",
                    revision=revision,
                ).to_node()
                claim_id = identifier("assertion")
                citation = EvidenceRecord(
                    id=identifier("evidence"),
                    assertion_id=claim_id,
                    source_id=source.id,
                    source_revision=revision,
                    excerpt=string(f"Wheel count reported as {count}"),
                ).to_node()
                claim = AssertionRecord(
                    id=claim_id,
                    subject=vehicle.id,
                    predicate=VEHICLE + "wheelCount",
                    object=LiteralValue(lexical=str(count), datatype=XSD + "integer"),
                    origin="imported",
                    evidence_ids=[citation.id],
                    valid_interval=interval.id,
                ).to_node()
                sources.append(source)
                evidence.append(citation)
                claims.append(claim)
            conflict = await new_changeset(
                case,
                [create(record, scope) for record in (*sources, *evidence, *claims)],
            )
            assert (await _validated(case, conflict["id"]))["state"] == "validated"
            conflict_report = await case.request(
                "GET", changeset_path(conflict["id"], "validation"), actor="bob"
            )
            assert "C1-CS-020" in {d["code"] for d in conflict_report.json()["diagnostics"]}
            await action(case, conflict["id"], "approve", actor="carol")
            assert (await action(case, conflict["id"], "apply", actor="carol"))[
                "state"
            ] == "applied"
            for claim in claims:
                assert (await case.request("GET", path(claim.id), actor="alice")).status_code == 200
            for record in (*sources, *evidence):
                assert (
                    await case.request("GET", path(record.id), actor="alice")
                ).status_code == 200

    asyncio.run(run())


def test_t07_schema_commit_crash_blocks_reads_until_recovery() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T07 schema guard")
            existing = entity_record(label="Existing readable content")
            await case.provision(existing, scope)
            assert (await case.request("GET", path(existing.id), actor="alice")).status_code == 200
            for name in ("erin", "frank"):
                principal = await case.principal(name)
                await case.fga.write(
                    [(principal.id, "schema_admin", "instance:" + case.settings.instance_id)]
                )
            install = await new_changeset(
                case, [{"kind": "install_profile", "profile": "example-vehicle"}], actor="erin"
            )
            assert (await _validated(case, install["id"], actor="erin"))["state"] == "validated"
            await action(case, install["id"], "approve", actor="frank")
            schema_before = await case.knowledge.schema_documents()
            await case.runtime.close()
            try:
                await _api_up(case, "commit")
                pid = api_process._pid()
                assert pid is not None and api_process._owned_process(pid)
                async with httpx.AsyncClient(
                    base_url="http://127.0.0.1:18000", timeout=client_timeout(), trust_env=False
                ) as child:
                    frank = bearer(await case.token("frank"))
                    with pytest.raises(httpx.HTTPError):
                        await child.post(
                            changeset_path(install["id"], "apply"),
                            headers={**frank, "Idempotency-Key": uuid.uuid4().hex},
                        )
                    deadline = time.monotonic() + 10
                    while api_process._owned_process(pid) and time.monotonic() < deadline:
                        await asyncio.sleep(0.1)
                    assert not api_process._owned_process(pid)
                    assert await case.knowledge.schema_documents() != schema_before
                    pending = await case.journal.get("ChangeSet", install["id"])
                    assert pending is not None and pending["state"] == "applying"

                    # Inspect the durable half-install through public routes
                    # before starting recovery. Startup is intentionally not
                    # run for this read-only inspection app.
                    inspection_runtime = Runtime(case.settings)
                    inspection_app = create_app(case.settings, runtime=inspection_runtime)
                    try:
                        async with httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=inspection_app),
                            base_url="http://c1.test",
                            timeout=client_timeout(),
                        ) as inspection:
                            alice = bearer(await case.token("alice"))
                            guarded = await inspection.get(path(existing.id), headers=alice)
                            assert guarded.status_code == 404
                            guarded_history = await inspection.get(
                                "/v1/history",
                                params={"resource_id": existing.id},
                                headers=alice,
                            )
                            assert guarded_history.status_code == 404
                            assert (await inspection.get("/v1/readyz")).status_code == 503
                    finally:
                        await inspection_runtime.close()

                    await _api_up(case, None)
                    dave = bearer(await case.token("dave"))
                    recovered = await child.post("/v1/security-operations/recover", headers=dave)
                    assert recovered.status_code == 200, recovered.text
                    assert (await child.get("/v1/readyz")).status_code == 200
                    alice = bearer(await case.token("alice"))
                    assert (await child.get(path(existing.id), headers=alice)).status_code == 200
                    final = await child.get(
                        changeset_path(install["id"]), headers=bearer(await case.token("erin"))
                    )
                    assert final.status_code == 200, final.text
                    assert final.json()["state"] == "applied"
            finally:
                await asyncio.to_thread(api_process.down)

    asyncio.run(run())
