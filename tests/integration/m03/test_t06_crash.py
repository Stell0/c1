"""M03-T06: a real API process dies and recovers a durable scope move."""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import patch

import httpx
import pytest

from c1.authorization.fga import resource_object, scope_object
from scripts import api as api_process
from scripts.stack import compose
from tests.integration.m03.conftest import (
    LiveCase,
    bearer,
    client_timeout,
    entity_record,
    live_case,
    resource_path,
)


def _process_environment(case: LiveCase) -> dict[str, str]:
    settings = case.settings
    return {
        "C1_INSTANCE_ID": settings.instance_id,
        "C1_INSTANCE_IRI_BASE": settings.instance_base,
        "C1_ISSUER": settings.issuer,
        "C1_ISSUER_ALIAS": settings.issuer_alias,
        "C1_AUDIENCE": settings.audience,
        "C1_FGA_URL": settings.fga_url,
        "C1_FGA_TOKEN": settings.fga_token,
        "C1_FGA_STORE": settings.fga_store,
        "C1_FGA_MODEL": settings.fga_model,
        "C1_TERMINUS_URL": settings.terminus_url,
        "C1_TERMINUS_PASSWORD": settings.terminus_password,
        "C1_ORGANIZATION": settings.organization,
        "C1_KNOWLEDGE_DATABASE": settings.knowledge_database,
        "C1_WORKFLOW_DATABASE": settings.workflow_database,
        "C1_LOCK_PATH": str(settings.lock_path),
        "C1_INDEPENDENT_REVIEW": "true",
        "C1_ENABLE_PROBE_ROUTES": "true",
    }


async def _api_up(case: LiveCase, crash_after: str | None) -> None:
    with patch.dict(os.environ, _process_environment(case)):
        await asyncio.to_thread(api_process.up, crash_after)


@pytest.mark.parametrize("point", ["journal", "tuple", "confirm"])
def test_t06_real_process_crash_and_recovery(point: str) -> None:
    async def run() -> None:
        async with live_case() as case:
            original = await case.scope("M03-T06 original")
            restricted = await case.scope("M03-T06 restricted")
            await case.grant(original, "alice", "reader")
            await case.grant(restricted, "frank", "access_admin")
            record = entity_record(label="Crash point " + point)
            await case.provision(record, original)
            proposal = await case.request(
                "POST",
                f"/v1/access-scopes/{restricted}/bindings",
                json={"resource_id": record.id},
            )
            assert proposal.status_code == 200, proposal.text
            op_id = proposal.json()["id"]
            approved = await case.request(
                "POST", f"/v1/security-operations/{op_id}/approve", actor="frank"
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["state"] == "approved"
            assert (
                await case.request("GET", resource_path(record.id), actor="alice")
            ).status_code == 200

            # Release the parent lifetime writer lock before the child starts.
            await case.runtime.close()
            paused = False
            try:
                await _api_up(case, point)
                pid = api_process._pid()
                assert pid is not None and api_process._owned_process(pid)
                async with httpx.AsyncClient(
                    base_url="http://127.0.0.1:18000", timeout=client_timeout(), trust_env=False
                ) as client:
                    erin = bearer(await case.token("erin"))
                    alice = bearer(await case.token("alice"))
                    dave = bearer(await case.token("dave"))
                    with pytest.raises(httpx.HTTPError):
                        await client.post(f"/v1/security-operations/{op_id}/apply", headers=erin)
                    deadline = time.monotonic() + 10
                    while api_process._owned_process(pid) and time.monotonic() < deadline:
                        await asyncio.sleep(0.1)
                    assert not api_process._owned_process(pid), "API child did not die"

                    durable = await case.journal.get("Operation", op_id)
                    assert durable is not None and durable["state"] == "pending"
                    binding = await case.journal.get("Binding", record.id)
                    assert binding is not None and binding["state"] == "transitioning"
                    expected_tuple = scope_object(original if point == "journal" else restricted)
                    assert await case.fga.bindings(resource_object(record.id)) == [expected_tuple]

                    # Hold the real authorization service unavailable across
                    # startup recovery. The HTTP process remains up but unready.
                    await asyncio.to_thread(compose, ["pause", "openfga"])
                    paused = True
                    await _api_up(case, None)
                    assert (await client.get("/v1/readyz")).status_code == 503
                    assert (
                        await client.get(resource_path(record.id), headers=alice)
                    ).status_code == 404
                    pending = await case.journal.get("Operation", op_id)
                    assert pending is not None and pending["state"] == "pending"

                    await asyncio.to_thread(compose, ["unpause", "openfga"])
                    paused = False
                    recovered = await client.post("/v1/security-operations/recover", headers=dave)
                    assert recovered.status_code == 200, recovered.text
                    assert (await client.get("/v1/readyz")).status_code == 200
                    final = await client.get(f"/v1/security-operations/{op_id}", headers=erin)
                    assert final.status_code == 200, final.text
                    assert final.json()["state"] == "applied"
                    assert await case.fga.bindings(resource_object(record.id)) == [
                        scope_object(restricted)
                    ]
                    assert (
                        await client.get(resource_path(record.id), headers=alice)
                    ).status_code == 404
                    assert (
                        await client.get(resource_path(record.id), headers=erin)
                    ).status_code == 200
            finally:
                if paused:
                    await asyncio.to_thread(compose, ["unpause", "openfga"])
                await asyncio.to_thread(api_process.down)

    asyncio.run(run())
