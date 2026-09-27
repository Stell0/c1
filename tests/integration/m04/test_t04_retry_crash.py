"""M04-T04: idempotency and real API-process crash recovery."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from unittest.mock import patch

import httpx
import pytest

from c1.authorization.fga import resource_object, scope_object
from c1.model.nodes import ValidatedBatch
from scripts import api as api_process
from tests.integration.m03.conftest import bearer
from tests.integration.m04.conftest import (
    LiveCase,
    action,
    changeset_path,
    create,
    entity_record,
    live_case,
    new_changeset,
    new_entity,
    path,
    seeded_scope,
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


def _receipts(log: list[dict[str, object]], changeset_id: str) -> list[dict[str, object]]:
    found = []
    for entry in log:
        try:
            message = json.loads(str(entry["message"]))
        except (ValueError, KeyError):
            continue
        if isinstance(message, dict) and message.get("changeset") == changeset_id:
            found.append(message)
    return found


def test_t04_create_idempotency_replays_without_duplicate() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M04-T04 replay")
            record = new_entity("Idempotent proposal")
            body = {
                "base_revision": await case.knowledge.head(),
                "operations": [create(record, scope)],
                "rationale": "Synthetic replay",
            }
            headers = {"Idempotency-Key": uuid.uuid4().hex}
            first = await case.request(
                "POST", "/v1/changesets", headers=headers, json=body, actor="bob"
            )
            assert first.status_code == 201, first.text
            replay = await case.request(
                "POST", "/v1/changesets", headers=headers, json=body, actor="bob"
            )
            assert replay.status_code == 200, replay.text
            assert replay.json()["id"] == first.json()["id"]
            assert replay.json()["replayed"] is True
            assert len(await case.journal.list("ChangeSet")) == 1
            different = await case.request(
                "POST",
                "/v1/changesets",
                headers=headers,
                json={**body, "rationale": "Different request"},
                actor="bob",
            )
            assert different.status_code == 422, different.text
            assert len(await case.journal.list("ChangeSet")) == 1

    asyncio.run(run())


@pytest.mark.parametrize("point", ["journal", "commit", "tuple", "confirm"])
def test_t04_crash_recovery_has_one_receipt(point: str) -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, f"M04-T04 {point}")
            record = new_entity(f"Crash after {point}")
            proposal = await new_changeset(case, [create(record, scope)])
            cs_id = proposal["id"]
            await action(case, cs_id, "submit")
            current = await case.request("GET", changeset_path(cs_id), actor="bob")
            if current.json()["state"] == "submitted":
                await action(case, cs_id, "validate")
            await action(case, cs_id, "approve", actor="carol")
            before = len(_receipts(await case.knowledge.log(), cs_id))
            assert before == 0
            await case.runtime.close()
            try:
                await _api_up(case, point)
                pid = api_process._pid()
                assert pid is not None and api_process._owned_process(pid)
                async with httpx.AsyncClient(
                    base_url="http://127.0.0.1:18000", timeout=10, trust_env=False
                ) as client:
                    carol = bearer(await case.token("carol"))
                    dave = bearer(await case.token("dave"))
                    with pytest.raises(httpx.HTTPError):
                        await client.post(
                            changeset_path(cs_id, "apply"),
                            headers={**carol, "Idempotency-Key": uuid.uuid4().hex},
                        )
                    deadline = time.monotonic() + 10
                    while api_process._owned_process(pid) and time.monotonic() < deadline:
                        await asyncio.sleep(0.1)
                    assert not api_process._owned_process(pid)
                    if point == "commit":
                        # Force receipt lookup beyond a single 20-entry log page.
                        for index in range(25):
                            unrelated = entity_record(label=f"Unrelated commit {index}")
                            await case.knowledge.upsert_records(
                                ValidatedBatch(records=[unrelated]),
                                case.runtime.registry,
                                expected_head=await case.knowledge.head(),
                                message=f"m04-unrelated-{index}",
                            )
                        assert not _receipts(await case.knowledge.log(start=0, count=20), cs_id)
                        assert (
                            len(_receipts(await case.knowledge.log(start=20, count=20), cs_id)) == 1
                        )
                    await _api_up(case, None)
                    recovered = await client.post("/v1/security-operations/recover", headers=dave)
                    assert recovered.status_code == 200, recovered.text
                    final = await client.get(changeset_path(cs_id), headers=carol)
                    assert final.status_code == 200, final.text
                    assert final.json()["state"] == "applied"
                    assert (await client.get(path(record.id), headers=carol)).status_code == 200
                    assert await case.fga.bindings(resource_object(record.id)) == [
                        scope_object(scope)
                    ]
                    receipts = _receipts(await case.knowledge.log(), cs_id)
                    assert len(receipts) == 1
                    assert receipts[0]["attempt"] == 1
            finally:
                await asyncio.to_thread(api_process.down)

    asyncio.run(run())
