"""M01-T02: a failed batch leaves no records or durable receipt."""

from __future__ import annotations

import asyncio
import json

import pytest

from probes.session import session
from probes.terminus import BackendError
from probes.writer import ProbeWriter, digest


def item(n: int, *, valid: bool = True) -> dict[str, object]:
    doc: dict[str, object] = {"@type": "Item", "@id": f"Item/t02_{n}", "value": n}
    if valid:
        doc["name"] = f"item {n}"
    return doc


def test_t02_atomic_batch_and_durable_receipt() -> None:
    async def scenario() -> None:
        async with session() as services:
            knowledge, workflow = services.knowledge, services.workflow
            writer = ProbeWriter(knowledge, workflow)
            base = await knowledge.head()
            baseline_log = await knowledge.log()
            baseline_docs = await knowledge.documents()
            invalid = [item(1), item(2), item(3, valid=False)]

            with pytest.raises(BackendError) as caught:
                await knowledge.insert(invalid, "changeset=t02-bad digest=bad", base)
            assert 400 <= caught.value.status_code < 500
            assert await knowledge.head() == base
            assert await knowledge.log() == baseline_log
            assert await knowledge.documents() == baseline_docs
            assert all([(await knowledge.get(f"Item/t02_{n}")) is None for n in (1, 2, 3)])
            assert await writer.find("t02-bad", "user:u", digest(invalid)) is None

            valid = [item(1), item(2), item(3)]
            committed = await writer.apply("t02-good", valid, base)
            after_log = await knowledge.log()
            assert len(after_log) == len(baseline_log) + 1
            assert committed == "branch:" + after_log[0]["identifier"]
            message = json.loads(after_log[0]["message"])
            assert message == {
                "m01": 1,
                "changeset": "t02-good",
                "principal": "user:u",
                "repository": knowledge.database,
                "digest": digest(valid),
            }
            assert await knowledge.head() == committed
            assert {doc["@id"] for doc in await knowledge.documents()} == {
                f"Item/t02_{n}" for n in (1, 2, 3)
            }
            assert sorted(doc["value"] for doc in await knowledge.documents()) == [1, 2, 3]
            receipts = await workflow.documents()
            assert len(receipts) == 1
            assert receipts[0]["knowledge_commit"] == committed
            assert receipts[0]["digest"] == digest(valid)
            assert await knowledge.head() == committed
            assert await knowledge.log() == after_log

    asyncio.run(scenario())
