"""M01-T03: stale heads fail and lost replies reconcile from durable log metadata."""

from __future__ import annotations

import asyncio

import pytest

from probes.session import session
from probes.terminus import BackendError
from probes.writer import ProbeWriter, digest


def item(id: str, value: int) -> dict[str, object]:
    return {"@type": "Item", "@id": id, "name": id, "value": value}


def test_t03_stale_base_and_lost_response() -> None:
    async def scenario() -> None:
        async with session() as services:
            knowledge, workflow = services.knowledge, services.workflow
            writer_a = ProbeWriter(knowledge, workflow)
            writer_b = ProbeWriter(knowledge, workflow)
            base_a = await knowledge.head()
            base_b = await knowledge.head()
            assert base_a == base_b

            first = await writer_a.apply("t03-first", [item("Item/t03_a", 1)], base_a)
            first_log = await knowledge.log()
            with pytest.raises(BackendError) as caught:
                await writer_b.apply("t03-stale", [item("Item/t03_b", 2)], base_b)
            assert caught.value.status_code == 400
            assert caught.value.error["api:error"]["@type"] == "api:DataVersionMismatch"
            assert await knowledge.head() == first
            assert await knowledge.log() == first_log
            assert await knowledge.get("Item/t03_b") is None

            lost_doc = [item("Item/t03_lost", 3)]
            with pytest.raises(ConnectionError, match="Injected lost commit acknowledgement"):
                await writer_a.apply("t03-lost", lost_doc, first, discard_response=True)
            committed_log = await knowledge.log()
            assert len(committed_log) == len(first_log) + 1
            durable_commit = "branch:" + committed_log[0]["identifier"]
            assert await knowledge.head() == durable_commit
            assert await writer_b.find("t03-lost", "user:u", digest(lost_doc)) == durable_commit
            assert await workflow.documents() != []  # first projection exists
            assert not any(
                receipt["changeset"] == "t03-lost" for receipt in await workflow.documents()
            )

            recovered = await writer_b.apply("t03-lost", lost_doc, first)
            assert recovered == durable_commit
            assert await knowledge.log() == committed_log
            assert (
                sum(receipt["changeset"] == "t03-lost" for receipt in await workflow.documents())
                == 1
            )
            with pytest.raises(ValueError, match="different payload"):
                await writer_b.apply("t03-lost", [item("Item/t03_other", 4)], durable_commit)
            assert await knowledge.log() == committed_log

            # A separate principal with the same key cannot claim the first receipt.
            assert await writer_b.find("t03-lost", "user:other", digest(lost_doc)) is None
            other_commit = await writer_b.apply(
                "t03-lost",
                [item("Item/t03_other", 4)],
                durable_commit,
                principal="user:other",
            )
            assert other_commit != durable_commit
            assert await writer_b.find("t03-lost", "user:u", digest(lost_doc)) == durable_commit

            # Probe beyond common default page lengths; reconciliation must find old receipts.
            for n in range(12):
                await knowledge.insert(
                    [item(f"Item/t03_filler_{n}", n)], f"filler {n}", await knowledge.head()
                )
            assert len(await knowledge.log()) == len(committed_log) + 13
            assert await writer_b.find("t03-lost", "user:u", digest(lost_doc)) == durable_commit

    asyncio.run(scenario())
