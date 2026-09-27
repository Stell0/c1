"""Pinned TerminusDB proof for bounded commit-log paging and document history."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from c1.model.nodes import ValidatedBatch
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from tests.integration.m02.conftest import live_knowledge
from tests.integration.m03.conftest import entity_record

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="requires pinned live stack"),
]


def test_log_pages_reach_old_receipt_and_history_tracks_each_commit() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        identifier = f"urn:c1:instance:dev:entity/{uuid4()}"
        async with live_knowledge(registry) as db:
            heads: list[str] = []
            for index in range(12):
                record = entity_record(identifier, label=f"M04 paging version {index}")
                message = f"m04-paging-receipt-{index}"
                head = await db.upsert_records(
                    ValidatedBatch(records=[record]),
                    registry,
                    expected_head=await db.head(),
                    message=message,
                )
                heads.append(head)

            page_size = 4
            pages = [
                await db.log(start=start, count=page_size)
                for start in (0, page_size, 2 * page_size)
            ]
            assert [len(page) for page in pages] == [page_size, page_size, page_size]
            flattened = [entry for page in pages for entry in page]
            assert len({entry["identifier"] for entry in flattened}) == len(flattened)
            assert [entry["identifier"] for entry in flattened[:12]] == [
                head.removeprefix("branch:") for head in reversed(heads)
            ]
            assert flattened[11]["message"] == "m04-paging-receipt-0"

            document_id = record_to_document(record, registry, db.config.instance_base)["@id"]
            history = await db.history(document_id)
            assert [entry["identifier"] for entry in history] == [
                head.removeprefix("branch:") for head in reversed(heads)
            ]
            assert [entry["message"] for entry in history] == [
                f"m04-paging-receipt-{index}" for index in reversed(range(12))
            ]

    asyncio.run(run())
