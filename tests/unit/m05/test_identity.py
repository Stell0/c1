"""Identity decisions preserve stable IDs and require complete assertion plans."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from c1.changes.identity import C1, RDF_SUBJECT, IdentityPlanError, expand_identity
from c1.changes.models import (
    AssertionAssignment,
    MergeOperation,
    ReplaceOperation,
    SplitOperation,
    UndoMergeOperation,
)
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, generated_classes
from c1.storage.terminus import Terminus
from tests.unit.m04.test_profiles import FakeClient

BASE = "urn:c1:instance:test:"
SURVIVOR = BASE + "entity/a"
MERGED = BASE + "entity/b"
CLAIM = BASE + "assertion/one"


def lit(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD_STRING)


def entity(identifier: str, label: str) -> NodeRecord:
    return NodeRecord(
        id=identifier,
        types=[C1 + "Entity"],
        properties={
            "http://www.w3.org/2004/02/skos/core#prefLabel": [lit(label)],
            C1 + "lifecycle": [lit("active")],
        },
    )


def claim() -> NodeRecord:
    return NodeRecord(
        id=CLAIM,
        types=[C1 + "Assertion"],
        properties={RDF_SUBJECT: [MERGED], C1 + "lifecycle": [lit("active")]},
    )


def test_merge_and_undo_expand_to_exact_replacements() -> None:
    async def case() -> None:
        records = {
            item.id: item
            for item in [entity(SURVIVOR, "Ada"), entity(MERGED, "A. Example"), claim()]
        }
        records[SURVIVOR] = records[SURVIVOR].model_copy(
            update={
                "properties": {
                    **records[SURVIVOR].properties,
                    "http://www.w3.org/2004/02/skos/core#altLabel": [lit("Already")],
                }
            }
        )
        records[MERGED] = records[MERGED].model_copy(
            update={
                "properties": {
                    **records[MERGED].properties,
                    "http://www.w3.org/2004/02/skos/core#altLabel": [lit("Former")],
                }
            }
        )

        async def resolve(identifier: str) -> NodeRecord | None:
            return records.get(identifier)

        async def authorize(_identifier: str) -> bool:
            return True

        async def assertions(subject: str) -> list[NodeRecord]:
            return [
                item for item in records.values() if item.properties.get(RDF_SUBJECT) == [subject]
            ]

        merge = MergeOperation(
            surviving_id=SURVIVOR,
            merged_id=MERGED,
            alias_plan="copy",
            assertion_plan=[AssertionAssignment(assertion_id=CLAIM, action="move")],
            rationale="same person",
            scope_id="shared",
        )
        expanded = await expand_identity(
            merge,
            base=BASE,
            actor=BASE + "actor/reviewer",
            resolve=resolve,
            authorize=authorize,
            list_assertions=assertions,
        )
        replacements = {
            item.resource_id: item for item in expanded if isinstance(item, ReplaceOperation)
        }
        assert set(replacements) == {SURVIVOR, MERGED, CLAIM}
        assert replacements[CLAIM].record["properties"][RDF_SUBJECT] == [SURVIVOR]
        assert (
            replacements[MERGED].record["properties"][C1 + "lifecycle"][0]["lexical"]
            == "superseded"
        )
        assert len(expanded) == 5
        resolution = NodeRecord.model_validate(expanded[-2].record)  # type: ignore[union-attr]
        redirect = NodeRecord.model_validate(expanded[-1].record)  # type: ignore[union-attr]
        assert redirect.properties["urn:c1:ns:identity#resolution"] == [resolution.id]
        assert redirect.properties[C1 + "lifecycle"] == [lit("active")]
        assert redirect.properties["urn:c1:ns:identity#copiedAlias"] == [
            lit("A. Example"),
            lit("Former"),
        ]

        records[resolution.id] = resolution
        records[redirect.id] = redirect
        records[CLAIM] = NodeRecord.model_validate(replacements[CLAIM].record)
        records[MERGED] = NodeRecord.model_validate(replacements[MERGED].record)
        merged_survivor = NodeRecord.model_validate(replacements[SURVIVOR].record)
        records[SURVIVOR] = merged_survivor.model_copy(
            update={
                "properties": {
                    **merged_survivor.properties,
                    "http://www.w3.org/2004/02/skos/core#altLabel": [
                        *merged_survivor.properties["http://www.w3.org/2004/02/skos/core#altLabel"],
                        lit("Later"),
                    ],
                }
            }
        )
        undo = UndoMergeOperation(
            resolution_id=resolution.id,
            reassignment_plan=[AssertionAssignment(assertion_id=CLAIM, action="move")],
            rationale="mistaken merge",
            scope_id="shared",
        )
        restored = await expand_identity(
            undo,
            base=BASE,
            actor=BASE + "actor/reviewer",
            resolve=resolve,
            authorize=authorize,
            list_assertions=assertions,
            all_records=list(records.values()),
        )
        restored_by_id = {
            item.resource_id: item for item in restored if isinstance(item, ReplaceOperation)
        }
        assert restored_by_id[CLAIM].record["properties"][RDF_SUBJECT] == [MERGED]
        assert (
            restored_by_id[redirect.id].record["properties"][C1 + "lifecycle"][0]["lexical"]
            == "retracted"
        )
        assert (
            restored_by_id[MERGED].record["properties"][C1 + "lifecycle"][0]["lexical"] == "active"
        )
        restored_survivor = NodeRecord.model_validate(restored_by_id[SURVIVOR].record)
        assert restored_survivor.properties["http://www.w3.org/2004/02/skos/core#altLabel"] == [
            lit("Already"),
            lit("Later"),
        ]

    asyncio.run(case())


def test_incomplete_or_unreadable_assertion_plan_fails_closed() -> None:
    async def case() -> None:
        records = {
            item.id: item
            for item in [entity(SURVIVOR, "Ada"), entity(MERGED, "A. Example"), claim()]
        }

        async def resolve(identifier: str) -> NodeRecord | None:
            return records.get(identifier)

        async def assertions(_subject: str) -> list[NodeRecord]:
            return [records[CLAIM]]

        async def allow(_identifier: str) -> bool:
            return True

        missing = MergeOperation(
            surviving_id=SURVIVOR,
            merged_id=MERGED,
            alias_plan="drop",
            assertion_plan=[],
            rationale="same person",
            scope_id="shared",
        )
        with pytest.raises(IdentityPlanError, match="Incomplete assertion reassignment"):
            await expand_identity(
                missing,
                base=BASE,
                actor=BASE + "actor/reviewer",
                resolve=resolve,
                authorize=allow,
                list_assertions=assertions,
            )

        async def hidden(identifier: str) -> bool:
            return identifier != CLAIM

        complete = missing.model_copy(
            update={"assertion_plan": [AssertionAssignment(assertion_id=CLAIM, action="move")]}
        )
        with pytest.raises(IdentityPlanError, match="Incomplete assertion reassignment"):
            await expand_identity(
                complete,
                base=BASE,
                actor=BASE + "actor/reviewer",
                resolve=resolve,
                authorize=hidden,
                list_assertions=assertions,
            )

    asyncio.run(case())


def test_identity_profile_loads_with_core() -> None:
    registry = ProfileRegistry()
    registry.load(Path("profiles/available/identity"))
    assert "urn:c1:ns:identity#Redirect" in registry.classes


def test_directory_and_identity_profiles_detect_together() -> None:
    async def case() -> None:
        from typing import cast

        from c1.changes.profiles import detect_installed_registry

        client = FakeClient(extension_schema=False, extension_marker=False)
        registry = ProfileRegistry()
        for name in ("directory", "identity"):
            registry.load(Path("profiles/available") / name)
            client.schema.extend(generated_classes(registry, name))
            marker = record_to_document(
                _profile_marker(registry, name), registry, client.config.instance_base
            )
            client.markers[str(marker["@id"])] = marker
        installed = await detect_installed_registry(cast(Terminus, client))
        assert set(installed.profiles) == {"core", "directory", "identity"}

    asyncio.run(case())


def test_split_keeps_source_identity_and_mints_new_entity() -> None:
    async def case() -> None:
        records = {MERGED: entity(MERGED, "Ada"), CLAIM: claim()}

        async def resolve(identifier: str) -> NodeRecord | None:
            return records.get(identifier)

        async def allow(_identifier: str) -> bool:
            return True

        async def assertions(_subject: str) -> list[NodeRecord]:
            return [records[CLAIM]]

        split = SplitOperation(
            source_id=MERGED,
            new_entity={
                "types": [C1 + "Entity"],
                "properties": {
                    "http://www.w3.org/2004/02/skos/core#prefLabel": [
                        lit("Other").model_dump(mode="json")
                    ],
                    C1 + "lifecycle": [lit("active").model_dump(mode="json")],
                },
            },
            assertion_plan=[AssertionAssignment(assertion_id=CLAIM, action="move")],
            rationale="different person",
            scope_id="shared",
        )
        expanded = await expand_identity(
            split,
            base=BASE,
            actor=BASE + "actor/reviewer",
            resolve=resolve,
            authorize=allow,
            list_assertions=assertions,
        )
        new_id = expanded[0].record["id"]  # type: ignore[union-attr]
        assert new_id.startswith(BASE + "entity/") and new_id != MERGED
        assert expanded[2].record["properties"][RDF_SUBJECT] == [new_id]  # type: ignore[union-attr]
        source_touch = next(
            item
            for item in expanded
            if isinstance(item, ReplaceOperation) and item.resource_id == MERGED
        )
        assert source_touch.record == records[MERGED].model_dump(mode="json")

    asyncio.run(case())
