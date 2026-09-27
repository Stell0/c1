"""M05-T01: one shared Person with assertions visible by current scope."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from c1.model.nodes import NodeRecord
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m04.conftest import action, changeset_path, new_changeset

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]
ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/directory/fixture.json"


async def _request_as_service(
    case: LiveCase,
    service_token: str,
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    merged = {"Authorization": "Bearer " + service_token, **(headers or {})}
    return await case.client.request(method, path, headers=merged, json=json_body)


async def _setup_directory(case: LiveCase, fixture: dict[str, Any]) -> None:
    carol = await case.principal("carol")
    erin = await case.principal("erin")
    for member in (erin.id, carol.id):
        response = await case.request(
            "POST",
            "/v1/instance/grants",
            actor="erin",
            json={"member": member, "role": "schema_admin"},
        )
        assert response.status_code == 200, response.text
    install = await new_changeset(
        case, [{"kind": "install_profile", "profile": fixture["profile"]}], actor="erin"
    )
    assert (await action(case, install["id"], "submit", actor="erin"))["state"] in {
        "submitted",
        "validated",
    }
    submitted = await case.request("GET", changeset_path(install["id"]), actor="erin")
    if submitted.json()["state"] == "submitted":
        assert (await action(case, install["id"], "validate", actor="erin"))["state"] == "validated"
    assert (await action(case, install["id"], "approve", actor="carol"))["state"] == "approved"
    assert (await action(case, install["id"], "apply", actor="carol"))["state"] == "applied"

    scopes: dict[str, str] = {}
    for name, label in fixture["scopes"].items():
        scope = await case.scope(label)
        scopes[name] = scope
        for principal_name in ("alice", "bob", "carol", "dave"):
            if name in fixture["principals"][principal_name]:
                await case.grant(scope, principal_name, "reader")
        await case.grant(scope, "carol", "reviewer")
    service_token = (await case.token_source.service("c1-svc-papertrader")).access
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

    operations = []
    for item in fixture["records"]:
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
    head = await case.knowledge.head()
    proposal = await _request_as_service(
        case,
        service_token,
        "POST",
        "/v1/changesets",
        json_body={
            "base_revision": head,
            "operations": operations,
            "rationale": "Load the deterministic directory integration fixture",
        },
        headers={"Idempotency-Key": "m05-t01-directory"},
    )
    assert proposal.status_code == 201, proposal.text
    changeset_id = proposal.json()["id"]
    submitted = await _request_as_service(
        case, service_token, "POST", changeset_path(changeset_id, "submit")
    )
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["state"] == "submitted":
        validated = await _request_as_service(
            case, service_token, "POST", changeset_path(changeset_id, "validate")
        )
        assert validated.status_code == 200, validated.text
    assert (await action(case, changeset_id, "approve", actor="carol"))["state"] == "approved"
    assert (
        await action(
            case,
            changeset_id,
            "apply",
            actor="carol",
            status=200,
        )
    )["state"] == "applied"


def test_t01_directory_shared_identity_and_authorized_assertions() -> None:
    async def run() -> None:
        fixture = cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))
        expected_assertions = cast(
            dict[str, list[str]],
            json.loads((FIXTURE.parent / "expected/assertions.json").read_text(encoding="utf-8")),
        )
        expected_export = cast(
            dict[str, list[str]],
            json.loads((FIXTURE.parent / "expected/export.json").read_text(encoding="utf-8")),
        )
        person_id = "urn:c1:instance:dev:entity/00000013-0000-4000-8000-000000000000"
        async with live_case() as case:
            await _setup_directory(case, fixture)
            person_histories: list[dict[str, Any]] = []
            for principal in ("alice", "bob", "carol", "dave"):
                search = await case.request(
                    "GET",
                    "/v1/entities",
                    actor=principal,
                    params={"label": "Ada Example", "label_mode": "exact", "limit": 10},
                )
                assert search.status_code == 200, search.text
                people = search.json()
                assert people["count"] == 1
                assert [item["id"] for item in people["items"]] == [person_id]

                assertions = await case.request(
                    "GET",
                    "/v1/assertions",
                    actor=principal,
                    params={"subject": person_id, "limit": 20},
                )
                assert assertions.status_code == 200, assertions.text
                payload = assertions.json()
                found = [item["id"] for item in payload["items"]]
                assert payload["count"] == len(expected_assertions[principal])
                assert found == expected_assertions[principal]

                export = await case.request(
                    "GET", "/v1/export", actor=principal, params={"limit": 50}
                )
                assert export.status_code == 200, export.text
                graph = export.json()["snapshot"].get("@graph", [])
                exported = sorted(item["@id"] for item in graph)
                assert export.json()["count"] == len(expected_export[principal])
                assert exported == expected_export[principal]

                history = await case.request(
                    "GET",
                    "/v1/history",
                    actor=principal,
                    params={"resource_id": person_id, "limit": 20},
                )
                assert history.status_code == 200, history.text
                person_histories.append(history.json())
            assert all(history == person_histories[0] for history in person_histories[1:])

    asyncio.run(run())
