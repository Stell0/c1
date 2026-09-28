"""M06 document fixtures use isolated real knowledge and authorization services."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from c1.model.nodes import NodeRecord
from tests.integration.m03.conftest import LiveCase
from tests.integration.m04.conftest import changeset_path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = ROOT / "fixtures/scoped-document/fixture.json"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m06/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M06 real services require C1_STACK=1"))


def fixture_spec() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


async def _knowledge_log(case: LiveCase) -> list[dict[str, Any]]:
    return await case.knowledge.log()


async def _service_token(case: LiveCase) -> str:
    return (await case.token_source.service("c1-svc-papertrader")).access


async def _service_request(
    case: LiveCase,
    _token: str,
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    # M03 test tokens expire after five minutes; M06 performs long synthetic
    # fixture writes. Request a normal, freshly issued token for the same
    # dedicated fixture producer on every helper call.
    token = (await case.token_source.service("c1-svc-papertrader")).access
    request_headers = {"Authorization": "Bearer " + token, **(headers or {})}
    return await case.client.request(
        method,
        path,
        headers=request_headers,
        json=json_body,
    )


async def _apply_as_service(
    case: LiveCase, token: str, operations: list[dict[str, Any]], rationale: str
) -> dict[str, Any]:
    head = await case.knowledge.head()
    proposal = await _service_request(
        case,
        token,
        "POST",
        "/v1/changesets",
        json_body={"base_revision": head, "operations": operations, "rationale": rationale},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert proposal.status_code == 201, proposal.text
    changeset_id = proposal.json()["id"]
    submitted = await _service_request(case, token, "POST", changeset_path(changeset_id, "submit"))
    assert submitted.status_code == 200, submitted.text
    state = submitted.json().get("state")
    if state == "submitted":
        validated = await _service_request(
            case, token, "POST", changeset_path(changeset_id, "validate")
        )
        assert validated.status_code == 200, validated.text
        state = validated.json().get("state")
    if state != "validated":
        report = await _service_request(
            case, token, "GET", changeset_path(changeset_id, "validation")
        )
        diagnostic_codes = [item.get("code") for item in report.json().get("diagnostics", [])]
        raise AssertionError(f"M06 fixture ChangeSet state={state}; diagnostics={diagnostic_codes}")
    approved = await case.request("POST", changeset_path(changeset_id, "approve"), actor="carol")
    assert approved.status_code == 200, approved.text
    assert approved.json().get("state") == "approved", approved.text
    applied = await case.request(
        "POST",
        changeset_path(changeset_id, "apply"),
        actor="carol",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json().get("state") == "applied", applied.text
    return cast(dict[str, Any], applied.json())


async def _reject_as_service(
    case: LiveCase,
    token: str,
    operations: list[dict[str, Any]],
    diagnostic_code: str,
) -> None:
    head = await case.knowledge.head()
    log = await _knowledge_log(case)
    proposal = await _service_request(
        case,
        token,
        "POST",
        "/v1/changesets",
        json_body={
            "base_revision": head,
            "operations": operations,
            "rationale": "Expected M06 validation failure",
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert proposal.status_code == 201, proposal.text
    changeset_id = proposal.json()["id"]
    submitted = await _service_request(case, token, "POST", changeset_path(changeset_id, "submit"))
    assert submitted.status_code == 200, submitted.text
    state = submitted.json().get("state")
    if state == "submitted":
        validated = await _service_request(
            case, token, "POST", changeset_path(changeset_id, "validate")
        )
        assert validated.status_code == 200, validated.text
        state = validated.json().get("state")
    report = await _service_request(case, token, "GET", changeset_path(changeset_id, "validation"))
    assert report.status_code == 200, report.text
    codes = {item.get("code") for item in report.json().get("diagnostics", [])}
    assert state == "rejected" and diagnostic_code in codes, (state, sorted(codes))
    assert await case.knowledge.head() == head
    assert await _knowledge_log(case) == log


async def install_scoped_document(
    case: LiveCase, *, omit_hidden_parts: bool = False
) -> tuple[dict[str, Any], dict[str, str], str, str]:
    async def fresh_user_token(name: str) -> str:
        return (await case.token_source.user(name)).access

    # M03 caches one 300-second token per principal. M06 cases exceed that
    # lifetime, so refresh the same real principal token before every request.
    cast(Any, case).token = fresh_user_token
    fixture = fixture_spec()
    scopes: dict[str, str] = {}
    for key, label in fixture["scopes"].items():
        scope = await case.scope("M06 " + label + " " + uuid.uuid4().hex[:8])
        scopes[key] = scope
        for principal_name in ("alice", "bob", "carol", "dave"):
            if key in fixture["principals"][principal_name]:
                await case.grant(scope, principal_name, "reader")
        await case.grant(scope, "carol", "reviewer")

    service_token = await _service_token(case)
    service = await case.validator.authenticate(service_token)
    for scope in scopes.values():
        for role in ("creator", "contributor", "reader"):
            response = await case.request(
                "POST",
                f"/v1/access-scopes/{quote(scope, safe='')}/members",
                actor="erin",
                json={"member": service.id, "role": role},
            )
            assert response.status_code == 200, response.text

    operations: list[dict[str, Any]] = []
    omitted = {
        "urn:c1:instance:dev:document-part/00000073-0000-4000-8000-000000000000",
        "urn:c1:instance:dev:document-part/00000074-0000-4000-8000-000000000000",
        "urn:c1:instance:dev:document-part/00000075-0000-4000-8000-000000000000",
        "urn:c1:instance:dev:document-part/00000076-0000-4000-8000-000000000000",
    }
    for item in fixture["revision1"]:
        if omit_hidden_parts and item["id"] in omitted:
            continue
        record = NodeRecord.model_validate(
            {key: item[key] for key in ("id", "types", "properties")}
        )
        operations.append(
            {
                "kind": "create",
                "record": record.model_dump(mode="json"),
                "scope_id": scopes[item["scope"]],
            }
        )
    await _apply_as_service(
        case, service_token, operations, "Load synthetic scoped document revision 1"
    )
    revision1 = await case.knowledge.head()

    by_id = {item["id"]: item for item in fixture["revision1"]}
    replacements: list[dict[str, Any]] = []
    for change in fixture["revision2"]["changes"]:
        original = by_id[change["id"]]
        replacement_record: dict[str, Any] = {
            "id": original["id"],
            "types": original["types"],
            "properties": {**original["properties"], **change["properties"]},
        }
        replacements.append(
            {
                "kind": "replace",
                "resource_id": change["id"],
                "record": replacement_record,
                "reason": "Synthetic document update for revision 2",
            }
        )
    await _apply_as_service(
        case, service_token, replacements, "Load synthetic scoped document revision 2"
    )
    revision2 = await case.knowledge.head()
    return fixture, scopes, revision1, revision2
