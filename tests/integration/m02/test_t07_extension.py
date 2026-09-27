"""M02-T07: a data-only profile adds a class and rejects an incompatible revision."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from rdflib.compare import isomorphic

from c1.interchange import export_jsonld, graph_from_records, import_jsonld
from c1.model.profiles import ProfileRegistry, compare_profiles
from c1.storage.terminus import StorageError
from tests.integration.m02.conftest import ROOT, live_knowledge

PROFILE_DIR = ROOT / "tests/fixtures/profiles/example-vehicle"
INCOMPATIBLE_DIR = ROOT / "tests/fixtures/profiles/example-vehicle-v2-incompatible"


def _vehicle_fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((PROFILE_DIR / "vehicle.jsonld").read_text()))


def test_t07_additive_profile_roundtrip_and_incompatible_revision() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        registry.load(PROFILE_DIR)
        vehicle = import_jsonld(_vehicle_fixture(), registry)
        assert len(vehicle.records) == 1
        assert vehicle.diagnostics == []

        incompatible = ProfileRegistry()
        incompatible.load(INCOMPATIBLE_DIR)
        differences = compare_profiles(
            registry.profiles["example-vehicle"], incompatible.profiles["example-vehicle"]
        )
        assert any(
            item.code == "C1-PR-004" and "MigrationRequired" in item.message for item in differences
        )

        async with live_knowledge(ProfileRegistry()) as db:
            await db.add_profile(registry, "example-vehicle")
            committed = await db.write_records(vehicle, registry, expected_head=await db.head())
            restored = await db.read_records(registry)
            assert len(restored) == 1
            assert restored[0].id == vehicle.records[0].id
            assert isomorphic(graph_from_records(vehicle.records), graph_from_records(restored))
            exported = export_jsonld(restored, registry)
            assert all(
                node["@id"].startswith("urn:c1:instance:dev:") for node in exported["@graph"]
            )
            assert "terminusdb:///" not in str(exported)
            assert isomorphic(
                graph_from_records(vehicle.records),
                graph_from_records(import_jsonld(exported, registry).records),
            )

            schema_before = await db.schema_documents()
            log_before = await db.log()
            with pytest.raises(StorageError, match="C1-ST-006"):
                await db.add_profile(incompatible, "example-vehicle")
            assert await db.head() == committed
            assert await db.log() == log_before
            assert await db.schema_documents() == schema_before

    asyncio.run(run())


def test_t07_core_implementation_has_no_extension_name() -> None:
    for file in (ROOT / "src/c1").rglob("*.py"):
        assert "vehicle" not in file.read_text(encoding="utf-8").lower(), file
