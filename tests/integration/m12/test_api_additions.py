"""M12 D7 live checks: schema, the caller's scopes, and security operations to act on."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from tests.integration.m03.conftest import LiveCase
from tests.integration.m11.conftest import accept, draft_operations, fixture_check, propose, rescope
from tests.integration.software import Template, copy_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M12 real services required"),
]


async def _mine(case: LiveCase, actor: str) -> dict[str, list[str]]:
    response = await case.request("GET", "/v1/access-scopes/mine", actor=actor)
    assert response.status_code == 200, response.text
    items = response.json()["access_scopes"]
    for item in items:
        assert set(item) == {"id", "label", "kind", "roles"}
    return {item["id"]: item["roles"] for item in items}


async def _operations(case: LiveCase, actor: str) -> list[str]:
    response = await case.request("GET", "/v1/security-operations", actor=actor)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is False
    for item in body["security_operations"]:
        assert "payload" not in item
    return [item["id"] for item in body["security_operations"]]


def test_api_additions_list_only_what_the_caller_can_act_on(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            schema = await case.request("GET", "/v1/schema", actor="alice")
            assert schema.status_code == 200, schema.text
            body = schema.json()
            assert set(body) == {"instance", "profiles", "available_profiles"}
            assert "software" in [p["name"] for p in body["profiles"]]
            assert "example-hostile-hints" in body["available_profiles"]
            assert "sw-" not in schema.text  # No scope, record or instance data.

            assert await _mine(case, "alice") == {
                "sw-shared": ["reader"],
                "sw-docs": ["reader"],
                "sw-publications": ["reader"],
            }
            assert await _mine(case, "frank") == {"sw-docs": ["access_admin"]}
            erin = await _mine(case, "erin")
            assert "sw-docs" not in erin
            for scope in ("sw-shared", "sw-ledger", "sw-shop", "sw-restricted", "drafts-bob"):
                assert "access_admin" in erin[scope]
            carol = await _mine(case, "carol")
            assert "access_admin" in carol["drafts-bob"] and "access_admin" in carol["sw-docs"]
            assert "reviewer" in carol["sw-restricted"]

            # The M11 draft widening: Carol proposes, Frank (destination) and Erin
            # (lineage) may approve; Alice and Dave are not involved.
            bob = (await case.principal("bob")).id
            operations, ids = draft_operations(
                software_template, bob, check=fixture_check(software_template), lineage=True
            )
            status, view = await propose(case, "bob", operations)
            assert status == 200, view
            await accept(case, view, "dave")
            proposal: dict[str, Any] = await rescope(case, ids["document"], "sw-docs", "carol")
            operation = proposal["id"]
            for actor in ("carol", "frank", "erin"):
                assert operation in await _operations(case, actor), actor
            for actor in ("alice", "dave"):
                assert operation not in await _operations(case, actor), actor
            lineage_read = await case.request(
                "GET", f"/v1/security-operations/{operation}", actor="erin"
            )
            assert lineage_read.status_code == 200, lineage_read.text
            outsider = await case.request(
                "GET", f"/v1/security-operations/{operation}", actor="alice"
            )
            assert outsider.status_code == 403

            # Both listings fail closed when the authorization service is unavailable.
            async def unavailable(*_args: Any, **_kwargs: Any) -> Any:
                raise OSError("authorization service unavailable")

            fga = case.runtime.fga
            original_batch, original_check = fga.batch_check, fga.check
            fga.batch_check, fga.check = unavailable, unavailable
            try:
                mine = await case.request("GET", "/v1/access-scopes/mine", actor="alice")
                ops = await case.request("GET", "/v1/security-operations", actor="frank")
                assert mine.status_code == 503 and ops.status_code == 503
            finally:
                fga.batch_check, fga.check = original_batch, original_check

    asyncio.run(run())
