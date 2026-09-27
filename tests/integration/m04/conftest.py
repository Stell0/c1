"""Real-stack M04 helpers, with fresh M03-style databases and FGA store per test."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

import pytest

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import AssertionRecord, EvidenceRecord, SourceRecord
from tests.integration.m03.conftest import (
    LiveCase,
    entity_record,
    live_case,
)

C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/core-knowledge/changesets/reviewed-assertions.json"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m04/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M04 real services require C1_STACK=1"))


def identifier(kind: str) -> str:
    return f"urn:c1:instance:dev:{kind}/{uuid.uuid4()}"


def new_entity(label: str) -> NodeRecord:
    return entity_record(identifier("entity"), label=label)


def string(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + "string")


def fixture_spec() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))


def source_record() -> NodeRecord:
    spec = fixture_spec()["source"]
    return SourceRecord(
        id=identifier("source"),
        title=string(spec["title"]),
        kind=spec["kind"],
        revision=spec["revision"],
    ).to_node()


def evidence_record(assertion_id: str, source_id: str) -> NodeRecord:
    spec = fixture_spec()["evidence"]
    return EvidenceRecord(
        id=identifier("evidence"),
        assertion_id=assertion_id,
        source_id=source_id,
        source_revision=spec["source_revision"],
        excerpt=string(spec["excerpt"]),
    ).to_node()


def assertion_record(
    subject: str,
    *,
    assertion_id: str | None = None,
    object_id: str | None = None,
    origin: Literal["manual", "imported", "derived"] = "manual",
    evidence_ids: list[str] | None = None,
    attributed_to: str | None = None,
    manual_statement: bool = True,
    predicate: str = C1 + "worksFor",
) -> NodeRecord:
    return AssertionRecord(
        id=assertion_id or identifier("assertion"),
        subject=subject,
        predicate=predicate,
        object=object_id or subject,
        origin=origin,
        evidence_ids=evidence_ids or [],
        attributed_to=attributed_to,
        manual_statement=manual_statement,
    ).to_node()


def create(record: NodeRecord, scope: str) -> dict[str, Any]:
    return {"kind": "create", "record": record.model_dump(mode="json"), "scope_id": scope}


def replace(record: NodeRecord, reason: str = "Synthetic correction") -> dict[str, Any]:
    return {
        "kind": "replace",
        "resource_id": record.id,
        "record": record.model_dump(mode="json"),
        "reason": reason,
    }


def path(identifier_value: str) -> str:
    return "/v1/resources/" + quote(identifier_value, safe="")


def changeset_path(changeset_id: str, action: str = "") -> str:
    base = "/v1/changesets/" + quote(changeset_id, safe="")
    return base + ("/" + action if action else "")


async def new_changeset(
    case: LiveCase,
    operations: list[dict[str, Any]],
    *,
    actor: str = "bob",
    base_revision: str | None = None,
    restores_from_revision: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "base_revision": base_revision or await case.knowledge.head(),
        "operations": operations,
        "rationale": "Synthetic M04 integration fixture",
    }
    if restores_from_revision is not None:
        body["restores_from_revision"] = restores_from_revision
    response = await case.request(
        "POST",
        "/v1/changesets",
        actor=actor,
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
        json=body,
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def action(
    case: LiveCase,
    changeset_id: str,
    name: str,
    *,
    actor: str = "bob",
    status: int = 200,
) -> dict[str, Any]:
    headers = {"Idempotency-Key": uuid.uuid4().hex} if name == "apply" else {}
    response = await case.request(
        "POST", changeset_path(changeset_id, name), actor=actor, headers=headers
    )
    assert response.status_code == status, response.text
    return cast(dict[str, Any], response.json())


async def reviewed_apply(case: LiveCase, changeset_id: str) -> dict[str, Any]:
    assert (await action(case, changeset_id, "submit"))["state"] in {"submitted", "validated"}
    current = await case.request("GET", changeset_path(changeset_id), actor="bob")
    assert current.status_code == 200, current.text
    if current.json()["state"] == "submitted":
        assert (await action(case, changeset_id, "validate"))["state"] == "validated"
    assert (await action(case, changeset_id, "approve", actor="carol"))["state"] == "approved"
    return await action(case, changeset_id, "apply", actor="carol")


async def seeded_scope(case: LiveCase, label: str) -> str:
    scope = await case.scope(label)
    for person, role in (
        ("alice", "reader"),
        ("bob", "creator"),
        ("bob", "contributor"),
        ("bob", "reader"),
        ("carol", "reviewer"),
        ("carol", "reader"),
    ):
        await case.grant(scope, person, role)
    return scope


__all__ = [
    "C1",
    "RDF",
    "XSD",
    "LiveCase",
    "action",
    "assertion_record",
    "changeset_path",
    "create",
    "entity_record",
    "evidence_record",
    "fixture_spec",
    "identifier",
    "live_case",
    "new_changeset",
    "new_entity",
    "path",
    "replace",
    "reviewed_apply",
    "seeded_scope",
    "source_record",
    "string",
]
