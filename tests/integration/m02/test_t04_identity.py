"""M02-T04: mutable descriptions and duplicate candidates do not rewrite identity."""

from __future__ import annotations

import asyncio
import copy

from c1.interchange import import_jsonld
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from tests.integration.m02.conftest import expected, fixture_payload, live_knowledge

C1 = "urn:c1:ns:core#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
INSTANCE_BASE = "urn:c1:instance:dev:"


def test_t04_identity_survives_label_project_and_scope_hint_changes() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        source = fixture_payload()
        identities = expected("identities.json")
        original_payload = {"@context": source["@context"], "@graph": source["@graph"][:8]}
        original_batch = import_jsonld(original_payload, registry)
        original_tesla = next(
            item for item in original_batch.records if item.id == identities["tesla"]
        )
        original_storage = record_to_document(original_tesla, registry, INSTANCE_BASE)["@id"]

        async with live_knowledge(registry) as db:
            await db.write_records(original_batch, registry, expected_head=await db.head())
            restored = {item.id: item for item in await db.read_records(registry)}
            assert identities["tesla"] in restored
            assert await db.get(original_storage) is not None

        changed_payload = copy.deepcopy(original_payload)
        changed_tesla = changed_payload["@graph"][0]
        changed_tesla[SKOS + "prefLabel"] = [
            {"@value": "Tesla renamed", "@language": "en"},
            {"@value": "Tesla umbenannt", "@language": "de"},
        ]
        changed_tesla[C1 + "projectReference"] = {"@id": "urn:c1:project:fixture-project"}
        changed_tesla[C1 + "provisionedScopeHint"] = {"@id": "urn:c1:scope:historical-hint-only"}
        duplicate = copy.deepcopy(changed_tesla)
        duplicate["@id"] = "urn:c1:instance:dev:entity/00000004-0000-4000-8000-000000000000"
        changed_payload["@graph"].append(duplicate)
        changed_batch = import_jsonld(changed_payload, registry)
        changed_records = {item.id: item for item in changed_batch.records}
        assert identities["tesla"] in changed_records
        assert duplicate["@id"] in changed_records
        assert changed_records[identities["tesla"]].id != changed_records[duplicate["@id"]].id
        changed_storage = record_to_document(
            changed_records[identities["tesla"]], registry, INSTANCE_BASE
        )["@id"]
        duplicate_storage = record_to_document(
            changed_records[duplicate["@id"]], registry, INSTANCE_BASE
        )["@id"]
        assert changed_storage == original_storage
        assert duplicate_storage != original_storage
        assert any(
            item.code == "C1-IX-040" and item.severity == "info"
            for item in changed_batch.diagnostics
        )

        async with live_knowledge(registry) as db:
            await db.write_records(changed_batch, registry, expected_head=await db.head())
            restored = {item.id: item for item in await db.read_records(registry)}
            assert identities["tesla"] in restored
            assert duplicate["@id"] in restored
            assert await db.get(original_storage) is not None
            assert await db.get(duplicate_storage) is not None
            assert restored[identities["tesla"]].properties[C1 + "projectReference"] == [
                "urn:c1:project:fixture-project"
            ]
            assert restored[identities["tesla"]].properties[C1 + "provisionedScopeHint"] == [
                "urn:c1:scope:historical-hint-only"
            ]
            assert not any(C1 + "ResolutionRecord" in record.types for record in restored.values())
            assert len(restored) == len(changed_batch.records)

    asyncio.run(run())
