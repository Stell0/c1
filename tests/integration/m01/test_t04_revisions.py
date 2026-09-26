"""M01-T04: immutable reads, history, diff, and deletion."""

from __future__ import annotations

import asyncio

from probes.session import session


def test_t04_independent_revisions() -> None:
    async def scenario() -> None:
        async with session() as services:
            db = services.knowledge
            item_id = "Item/t04_one"
            first_doc = {"@type": "Item", "@id": item_id, "name": "first", "value": 1}
            second_doc = {"@type": "Item", "@id": item_id, "name": "second", "value": 2}
            first = await db.insert([first_doc], "t04 version one", await db.head())
            second = await db.replace([second_doc], "t04 version two", first)

            at_first = await db.get(item_id, first)
            at_second = await db.get(item_id, second)
            current = await db.get(item_id)
            assert at_first is not None and at_first["value"] == 1
            assert at_second is not None and at_second["value"] == 2
            assert current is not None and current["value"] == 2
            assert [doc["value"] for doc in await db.documents(first)] == [1]
            assert [doc["value"] for doc in await db.documents(second)] == [2]

            history = await db.history(item_id)
            assert [entry["identifier"] for entry in history] == [
                second.removeprefix("branch:"),
                first.removeprefix("branch:"),
            ]
            assert [entry["message"] for entry in history] == ["t04 version two", "t04 version one"]
            differences = await db.diff(first, second)
            assert len(differences) == 1
            assert differences[0]["value"] == {"@op": "SwapValue", "@before": 1, "@after": 2}

            third = await db.delete_documents([item_id], "t04 delete", second)
            assert third != second
            assert await db.get(item_id) is None
            at_first = await db.get(item_id, first)
            at_second = await db.get(item_id, second)
            assert at_first is not None and at_first["value"] == 1
            assert at_second is not None and at_second["value"] == 2

    asyncio.run(scenario())
