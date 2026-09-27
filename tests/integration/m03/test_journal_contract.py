"""Real TerminusDB proof of journal transaction and historical read contracts."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from c1.authorization.journal import Journal, _document_id, _encode
from c1.interchange import export_jsonld, import_jsonld
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord, ValidatedBatch
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import BackendError, StorageConfig, Terminus
from probes.config import Settings
from tests.integration.m02.conftest import fixture_payload
from tests.integration.m03.conftest import entity_record, live_case, resource_path

_ENTITY = "urn:c1:ns:core#Entity"
_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _config(name: str) -> StorageConfig:
    settings = Settings.load()
    return StorageConfig(
        url=settings.terminus_url,
        password=settings.terminus_password,
        organization="admin",
        database=f"c1_m03_{name}_{uuid4().hex}",
        instance_base="urn:c1:instance:dev:",
    )


def test_journal_mixed_upsert_is_one_commit_and_stale_or_invalid_batch_is_atomic() -> None:
    async def run() -> None:
        async with Journal(_config("journal")) as journal:
            await journal.initialize()
            try:
                assert await journal.ready()
                before = await journal.head()
                before_log = await journal._storage.log()
                first = await journal.save_many(
                    [
                        ("Scope", "scope-1", {"id": "scope-1", "status": "provisioning"}),
                        (
                            "Binding",
                            "resource-1",
                            {"resource_id": "resource-1", "scope": "scope-1"},
                        ),
                    ],
                    expected_head=before,
                )
                assert first != before
                assert await journal.head() == first
                assert len(await journal._storage.log()) == len(before_log) + 1
                assert await journal.get("Scope", "scope-1") == {
                    "id": "scope-1",
                    "status": "provisioning",
                }
                assert await journal.get("Binding", "resource-1") == {
                    "resource_id": "resource-1",
                    "scope": "scope-1",
                }

                second = await journal.save_many(
                    [
                        ("Scope", "scope-1", {"id": "scope-1", "status": "active"}),
                        ("Operation", "operation-1", {"id": "operation-1", "phase": "done"}),
                    ],
                    expected_head=first,
                )
                assert second != first
                assert len(await journal._storage.log()) == len(before_log) + 2
                assert await journal.get("Scope", "scope-1") == {
                    "id": "scope-1",
                    "status": "active",
                }
                assert await journal.get("Operation", "operation-1") == {
                    "id": "operation-1",
                    "phase": "done",
                }
                assert await journal.list("Binding") == [
                    {"resource_id": "resource-1", "scope": "scope-1"}
                ]

                stable_log = await journal._storage.log()
                stable_docs = await journal._storage.documents()
                with pytest.raises(BackendError):
                    await journal.save_many(
                        [("Scope", "scope-1", {"id": "scope-1", "status": "stale"})],
                        expected_head=first,
                    )
                assert await journal.head() == second
                assert await journal._storage.log() == stable_log
                assert await journal._storage.documents() == stable_docs

                # Bypass the application validator to prove the server rejects
                # the entire mixed batch when one typed document is invalid.
                invalid = {
                    "@type": "WorkflowEntry",
                    "@id": _document_id("Operation", "operation-invalid"),
                    "kind": "Operation",
                    "key": "operation-invalid",
                }
                with pytest.raises(BackendError):
                    await journal._storage._put(
                        [
                            _encode("Scope", "scope-1", {"id": "scope-1", "status": "bad"}),
                            invalid,
                        ],
                        expected_head=second,
                        message="M03 invalid batch probe",
                        create=True,
                    )
                assert await journal.head() == second
                assert await journal._storage.log() == stable_log
                assert await journal._storage.documents() == stable_docs
            finally:
                await journal.drop_test_database()

    asyncio.run(run())


def test_historical_record_read_preserves_old_revision() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        batch = import_jsonld(fixture_payload(), registry)
        original = next(record for record in batch.records if _ENTITY in record.types)
        async with Terminus(_config("history")) as db:
            await db.create()
            try:
                await db.install_profile(registry)
                first = await db.write_records(batch, registry, expected_head=await db.head())
                old = await db.get_record(original.id, registry, commit=first)
                assert old is not None
                assert export_jsonld([old], registry) == export_jsonld([original], registry)

                changed_properties = dict(original.properties)
                changed_properties[_LABEL] = [
                    LiteralValue(lexical="M03 revised label", datatype=_XSD_STRING)
                ]
                changed = original.model_copy(update={"properties": changed_properties})
                second = await db.replace_records(
                    ValidatedBatch(records=[changed]), registry, expected_head=first
                )
                assert second != first
                current = await db.get_record(original.id, registry)
                historical = await db.get_record(original.id, registry, commit=first)
                assert current is not None and historical is not None
                assert export_jsonld([current], registry) == export_jsonld([changed], registry)
                assert export_jsonld([historical], registry) == export_jsonld([original], registry)
            finally:
                await db.drop()

    asyncio.run(run())


def test_multilingual_probe_publication_and_revision_preserve_exact_terms() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        initial = entity_record(label="English v1")
        properties = dict(initial.properties)
        properties[_LABEL] = [
            LiteralValue(
                lexical="English v1",
                datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                language="en",
            ),
            LiteralValue(
                lexical="Français v1",
                datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                language="fr",
            ),
        ]
        record = initial.model_copy(update={"properties": properties})
        revised_properties = dict(properties)
        revised_properties[_LABEL] = [
            LiteralValue(
                lexical="Français v1",
                datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                language="fr",
            ),
            LiteralValue(
                lexical="English v2",
                datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                language="en",
            ),
        ]
        revised = record.model_copy(update={"properties": revised_properties})
        async with live_case() as case:
            scope = await case.scope("M03 multilingual publication")
            creation = await case.provision(record, scope)
            old_revision = creation["revision"]
            current = await case.request("GET", resource_path(record.id))
            assert current.status_code == 200, current.text
            assert export_jsonld([NodeRecord.model_validate(current.json())], registry) == (
                export_jsonld([record], registry)
            )

            updated = await case.request(
                "PUT", resource_path(record.id), json={"record": revised.model_dump(mode="json")}
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["revision"] != old_revision
            new_read = await case.request("GET", resource_path(record.id))
            old_read = await case.request(
                "GET", resource_path(record.id) + "?revision=" + old_revision
            )
            assert new_read.status_code == 200, new_read.text
            assert old_read.status_code == 200, old_read.text
            assert export_jsonld([NodeRecord.model_validate(new_read.json())], registry) == (
                export_jsonld([revised], registry)
            )
            assert export_jsonld([NodeRecord.model_validate(old_read.json())], registry) == (
                export_jsonld([record], registry)
            )

    asyncio.run(run())
