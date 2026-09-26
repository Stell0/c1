"""M01-T06: interrupted publication remains unreadable until reconciliation."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from probes.config import ROOT
from probes.publication import Publisher, journal_id
from probes.session import Session, session
from probes.terminus import BackendError

USER = "user:t06_reader"
SCOPE = "scope:t06_shared"


def run_cli(
    services: Session, action: str, resource: str, crash: str | None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if crash is None:
        env.pop("C1_PROBE_CRASH_AFTER", None)
    else:
        env["C1_PROBE_CRASH_AFTER"] = crash
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "probes.publication",
            action,
            "--knowledge",
            services.knowledge.database,
            "--workflow",
            services.workflow.database,
            "--store",
            str(services.fga.store_id),
            "--model",
            str(services.fga.model_id),
            "--resource",
            resource,
            "--scope",
            SCOPE,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("crash", ["journal", "content", "binding"])
def test_t06_reconcile_after_process_crash(crash: str) -> None:
    async def scenario() -> None:
        async with session() as services:
            knowledge, workflow, fga = services.knowledge, services.workflow, services.fga
            await fga.write([(USER, "reader", SCOPE)])
            resource = "Item/t06_" + crash
            baseline_log = await knowledge.log()

            crashed = run_cli(services, "publish", resource, crash)
            assert crashed.returncode == 86, crashed.stderr
            journal = await workflow.get(journal_id(resource))
            assert journal is not None
            assert journal["state"] != "complete"
            reader = Publisher(knowledge, workflow, fga)
            assert await reader.read(resource, USER) is None

            recovered = run_cli(services, "reconcile", resource, None)
            assert recovered.returncode == 0, recovered.stderr
            latency = json.loads(recovered.stdout)["journal_write_ms"]
            print(json.dumps({"crash": crash, "journal_write_ms": latency}))
            assert latency and all(isinstance(ms, (int, float)) and ms > 0 for ms in latency)
            journal = await workflow.get(journal_id(resource))
            assert journal is not None and journal["state"] == "complete"
            assert await fga.bindings("resource:" + resource) == [SCOPE]
            assert await fga.check(USER, "reader", "resource:" + resource)

            commit = journal["knowledge_commit"]
            assert commit.startswith("branch:")
            assert await knowledge.head() == commit
            assert len(await knowledge.log()) == len(baseline_log) + 1
            matching = [
                row
                for row in await knowledge.log()
                if row["message"].startswith("{")
                and json.loads(row["message"]).get("changeset") == journal_id(resource)
            ]
            assert len(matching) == 1
            assert "branch:" + matching[0]["identifier"] == commit
            current = await Publisher(knowledge, workflow, fga).read(resource, USER)
            assert current is not None and current["value"] == 1

            knowledge_log = await knowledge.log()
            workflow_log = await workflow.log()
            repeated = run_cli(services, "reconcile", resource, None)
            assert repeated.returncode == 0, repeated.stderr
            assert await knowledge.head() == commit
            assert await knowledge.log() == knowledge_log
            assert await workflow.log() == workflow_log
            assert await Publisher(knowledge, workflow, fga).read(resource, USER) == current

    asyncio.run(scenario())


def test_t06_invalid_content_leaves_durable_deny_tombstone() -> None:
    async def scenario() -> None:
        async with session() as services:
            knowledge, workflow, fga = services.knowledge, services.workflow, services.fga
            await fga.write([(USER, "reader", SCOPE)])
            resource = "Item/t06_invalid"
            baseline_head = await knowledge.head()
            baseline_log = await knowledge.log()
            publisher = Publisher(knowledge, workflow, fga)

            with pytest.raises(BackendError) as caught:
                await publisher.publish({"@type": "Item", "@id": resource, "value": 1}, SCOPE)
            assert 400 <= caught.value.status_code < 500
            journal = await workflow.get(journal_id(resource))
            assert journal is not None and journal["state"] == "failed"
            assert await knowledge.head() == baseline_head
            assert await knowledge.log() == baseline_log
            assert await knowledge.get(resource) is None
            assert await fga.bindings("resource:" + resource) == []
            assert await Publisher(knowledge, workflow, fga).read(resource, USER) is None

    asyncio.run(scenario())
