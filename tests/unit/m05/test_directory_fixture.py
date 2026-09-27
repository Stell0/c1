"""Frozen contract and profile validation for the shared-directory fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from c1.interchange import validate_records
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/directory/fixture.json"


def test_directory_fixture_validates_and_freezes_principal_views() -> None:
    fixture = cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))
    registry = ProfileRegistry()
    registry.load(ROOT / "profiles/available/directory")
    records = [
        NodeRecord.model_validate({key: value for key, value in item.items() if key != "scope"})
        for item in fixture["records"]
    ]
    batch = validate_records(records, registry)

    assert len(batch.records) == 8
    assert len(fixture["records"]) == len(batch.records)
    person = next(
        record
        for record in batch.records
        if record.id.endswith("00000013-0000-4000-8000-000000000000")
    )
    assert "https://schema.org/Person" in person.types

    scopes = fixture["scopes"]
    assert fixture["principals"] == {
        "alice": ["dir-shared", "dir-company-a"],
        "bob": ["dir-shared", "dir-company-b"],
        "carol": list(scopes),
        "dave": ["dir-shared", "dir-selected"],
    }
    expected = cast(
        dict[str, list[str]],
        json.loads((FIXTURE.parent / "expected/assertions.json").read_text(encoding="utf-8")),
    )
    assert {name: len(ids) for name, ids in expected.items()} == {
        "alice": 3,
        "bob": 2,
        "carol": 5,
        "dave": 2,
    }
    assert len({item["id"] for item in fixture["records"]}) == len(fixture["records"])


def test_directory_fixture_has_expected_scope_partition() -> None:
    fixture = cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))
    scope_by_id = {item["id"]: item["scope"] for item in fixture["records"]}
    assert (
        scope_by_id["urn:c1:instance:dev:entity/00000013-0000-4000-8000-000000000000"]
        == "dir-shared"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:entity/00000011-0000-4000-8000-000000000000"]
        == "dir-company-a"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:entity/00000012-0000-4000-8000-000000000000"]
        == "dir-company-b"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:assertion/00000021-0000-4000-8000-000000000000"]
        == "dir-shared"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:assertion/00000022-0000-4000-8000-000000000000"]
        == "dir-company-a"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:assertion/00000023-0000-4000-8000-000000000000"]
        == "dir-company-b"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:assertion/00000024-0000-4000-8000-000000000000"]
        == "dir-company-a"
    )
    assert (
        scope_by_id["urn:c1:instance:dev:assertion/00000025-0000-4000-8000-000000000000"]
        == "dir-selected"
    )
