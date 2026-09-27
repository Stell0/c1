"""Trusted profile selection and startup detection of complete installations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from c1.changes.profiles import (
    available_profile_names,
    compare_candidate,
    detect_installed_registry,
    load_candidate,
)
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, generated_classes, generated_core_schema
from c1.storage.terminus import StorageConfig, StorageError, Terminus


class FakeClient:
    def __init__(self, *, extension_schema: bool, extension_marker: bool) -> None:
        self.config = StorageConfig(
            "http://localhost:6363", "unused", "admin", "c1_m04_test", "urn:c1:instance:dev:"
        )
        core = ProfileRegistry()
        candidate, _ = load_candidate("example-vehicle")
        self.schema = generated_core_schema(core)
        if extension_schema:
            self.schema.extend(generated_classes(candidate, "example-vehicle"))
        self.markers = {
            record_to_document(_profile_marker(core, "core"), core, self.config.instance_base)[
                "@id"
            ]: record_to_document(_profile_marker(core, "core"), core, self.config.instance_base)
        }
        if extension_marker:
            marker = record_to_document(
                _profile_marker(candidate, "example-vehicle"),
                candidate,
                self.config.instance_base,
            )
            self.markers[marker["@id"]] = marker

    async def schema_documents(self) -> list[dict[str, Any]]:
        return self.schema

    async def get(self, document_id: str, commit: str | None = None) -> dict[str, Any] | None:
        return self.markers.get(document_id)


def test_catalog_only_loads_fixed_local_aliases() -> None:
    assert available_profile_names() == (
        "example-vehicle",
        "example-vehicle-v2-incompatible",
    )
    registry, name = load_candidate("example-vehicle")
    assert name == "example-vehicle"
    assert set(registry.profiles) == {"core", name}
    with pytest.raises(ValueError, match="trusted local catalog"):
        load_candidate("../../tests/fixtures/profiles/example-vehicle")


def test_bundled_manifests_match_synthetic_fixture() -> None:
    root = Path(__file__).resolve().parents[3]
    for alias in available_profile_names():
        for filename in ("profile.json", "context.jsonld", "shapes.ttl"):
            bundled = root / "profiles" / "available" / alias / filename
            fixture = root / "tests" / "fixtures" / "profiles" / alias / filename
            assert bundled.read_bytes() == fixture.read_bytes()


def test_incompatible_candidate_requires_migration() -> None:
    installed, _ = load_candidate("example-vehicle")
    diagnostics = compare_candidate(installed, "example-vehicle-v2-incompatible")
    assert any(item.code == "C1-PR-004" for item in diagnostics)
    assert not any(
        item.code == "C1-PR-004" for item in compare_candidate(installed, "example-vehicle")
    )


@pytest.mark.parametrize(
    ("schema", "marker", "expected"),
    [
        (False, False, {"core"}),
        (True, True, {"core", "example-vehicle"}),
    ],
)
def test_detect_complete_installation(schema: bool, marker: bool, expected: set[str]) -> None:
    async def run() -> None:
        client = cast(Terminus, FakeClient(extension_schema=schema, extension_marker=marker))
        result = await detect_installed_registry(client)
        assert set(result.profiles) == expected

    asyncio.run(run())


@pytest.mark.parametrize(("schema", "marker"), [(False, True), (True, False)])
def test_detect_partial_installation_fails_closed(schema: bool, marker: bool) -> None:
    async def run() -> None:
        client = cast(Terminus, FakeClient(extension_schema=schema, extension_marker=marker))
        with pytest.raises(StorageError, match="C1-ST-006"):
            await detect_installed_registry(client)

    asyncio.run(run())


def test_detect_unknown_schema_fails_closed() -> None:
    async def run() -> None:
        fake = FakeClient(extension_schema=False, extension_marker=False)
        fake.schema.append({"@type": "Class", "@id": "Unknown"})
        with pytest.raises(StorageError, match="C1-ST-006"):
            await detect_installed_registry(cast(Terminus, fake))

    asyncio.run(run())
