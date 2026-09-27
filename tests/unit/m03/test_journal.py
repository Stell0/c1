"""Workflow envelope identity, validation, and pre-network guards."""

from __future__ import annotations

import asyncio

import pytest

from c1.authorization.journal import Journal, _decode, _document_id, _encode
from c1.storage.terminus import StorageConfig, StorageError, Terminus


def _config(database: str = "c1_m03_journal_unit") -> StorageConfig:
    return StorageConfig(
        url="http://127.0.0.1:16363",
        password="private-test-value",
        organization="admin",
        database=database,
        instance_base="urn:c1:instance:dev:",
    )


def test_distinct_typed_addresses_and_exact_payload_roundtrip() -> None:
    scope = _encode("Scope", "shared", {"id": "shared", "label": "Müller"})
    binding = _encode("Binding", "shared", {"resource_id": "shared", "state": "active"})
    assert scope["@id"] != binding["@id"]
    assert scope["@id"] == _document_id("Scope", "shared")
    assert _decode(scope) == ("Scope", "shared", {"id": "shared", "label": "Müller"})
    assert _decode(binding)[2]["state"] == "active"


@pytest.mark.parametrize("key", ["", "bad\nkey", "a" * 2049])
def test_invalid_address_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        _document_id("Scope", key)


def test_unknown_kind_and_non_json_payload_rejected() -> None:
    with pytest.raises(ValueError):
        _encode("Unknown", "x", {})
    with pytest.raises(ValueError):
        _encode("Scope", "x", {"number": float("nan")})
    with pytest.raises(ValueError):
        _encode("Scope", "x", {"object": object()})


def test_corrupt_envelope_fails_closed() -> None:
    document = _encode("Operation", "op-1", {"id": "op-1"})
    document["@id"] = "WorkflowEntry/wrong"
    with pytest.raises(StorageError, match="C1-JR-001"):
        _decode(document)
    document = _encode("Operation", "op-1", {"id": "op-1"})
    document["payload_json"] = "[]"
    with pytest.raises(StorageError, match="C1-JR-001"):
        _decode(document)


def test_duplicate_batch_rejected_before_network() -> None:
    async def run() -> None:
        async with Journal(_config()) as journal:
            with pytest.raises(ValueError, match="same kind/key twice"):
                await journal.save_many(
                    [
                        ("Binding", "resource-x", {"state": "provisioning"}),
                        ("Binding", "resource-x", {"state": "active"}),
                    ]
                )

    asyncio.run(run())


def test_m03_database_guard_keeps_production_names_out_of_create_drop() -> None:
    async def run() -> None:
        async with Terminus(_config("c1_m03_unit")) as test_client:
            assert test_client._database_path == "admin/c1_m03_unit"
        async with Terminus(_config("workflow")) as production_client:
            with pytest.raises(StorageError, match="C1-ST-007"):
                await production_client.create()
            with pytest.raises(StorageError, match="C1-ST-007"):
                await production_client.drop()

    asyncio.run(run())


def test_historical_commit_path_rejects_unsafe_identifier_before_network() -> None:
    async def run() -> None:
        async with Terminus(_config()) as client:
            with pytest.raises(ValueError, match="commit must be"):
                await client.get("WorkflowEntry/x", commit="../../other")

    asyncio.run(run())
