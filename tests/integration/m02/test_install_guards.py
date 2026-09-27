"""Live schema/marker failure and reserved-marker write guards."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from c1.interchange import import_jsonld
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord, ValidatedBatch
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import installed_profile_iri
from c1.storage.terminus import StorageConfig, StorageError, Terminus
from probes.config import Settings
from tests.integration.m02.conftest import fixture_payload, live_knowledge

_CORE = "urn:c1:ns:core#"
_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


class FailMarkerProjection(Terminus):
    async def _insert(
        self,
        documents: list[dict[str, Any]],
        *,
        expected_head: str,
        message: str,
        graph_type: str = "instance",
        full_replace: bool = False,
    ) -> str:
        if message == "Project C1 core profile version":
            raise StorageError("C1-ST-999", "injected marker projection failure")
        return await super()._insert(
            documents,
            expected_head=expected_head,
            message=message,
            graph_type=graph_type,
            full_replace=full_replace,
        )


def test_schema_commit_without_marker_fails_closed() -> None:
    async def run() -> None:
        settings = Settings.load()
        config = StorageConfig(
            url=settings.terminus_url,
            password=settings.terminus_password,
            organization="admin",
            database=f"c1_m02_marker_{uuid4().hex}",
            instance_base="urn:c1:instance:dev:",
        )
        registry = ProfileRegistry()
        batch = import_jsonld(fixture_payload(), registry)
        async with FailMarkerProjection(config) as db:
            await db.create()
            try:
                original_head = await db.head()
                with pytest.raises(StorageError, match="C1-ST-999"):
                    await db.install_profile(registry)
                committed_schema_head = await db.head()
                assert committed_schema_head != original_head
                assert await db.documents() == []
                log_after_schema = await db.log()
                assert len(log_after_schema) > 0

                with pytest.raises(StorageError, match="C1-ST-006"):
                    await db.read_records(registry)
                with pytest.raises(StorageError, match="C1-ST-006"):
                    await db.write_records(batch, registry, expected_head=committed_schema_head)
                assert await db.head() == committed_schema_head
                assert await db.log() == log_after_schema
                assert await db.documents() == []
            finally:
                await db.drop()

    asyncio.run(run())


def test_reserved_marker_cannot_be_written_as_ordinary_record() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        marker = NodeRecord(
            id=installed_profile_iri("core"),
            types=[_CORE + "SchemaProfile"],
            properties={
                _CORE + "profileName": [LiteralValue(lexical="core", datatype=_XSD_STRING)],
                _CORE + "profileVersion": [LiteralValue(lexical="1.0.0", datatype=_XSD_STRING)],
            },
        )
        async with live_knowledge(registry) as db:
            before_head = await db.head()
            before_log = await db.log()
            before_docs = await db.documents()
            with pytest.raises(StorageError, match="C1-ST-004"):
                await db.write_records(
                    ValidatedBatch(records=[marker]), registry, expected_head=before_head
                )
            assert await db.head() == before_head
            assert await db.log() == before_log
            assert await db.documents() == before_docs

    asyncio.run(run())
