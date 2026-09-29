"""M08 W1–W2: the data-only software profile and class-checked references."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from c1.authorization.models import Decision
from c1.changes.models import ChangeSet, CreateOperation
from c1.changes.profiles import load_candidate
from c1.changes.validation import reference_classes, validate_changeset
from c1.interchange import validate_records
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.references import required_class_references
from c1.storage.mapping import records_to_documents
from scripts.build_software_profile import TARGET, build_files

ROOT = Path(__file__).resolve().parents[3]
BASE = "urn:c1:instance:dev:"
C1 = "urn:c1:ns:core#"
S = "urn:c1:ns:software#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCT = "http://purl.org/dc/terms/"

REPOSITORY = BASE + "entity/0f6d7c1e-9d8a-4e1b-8c3a-1a2b3c4d5e6f"
SNAPSHOT = BASE + "entity/1f6d7c1e-9d8a-4e1b-8c3a-1a2b3c4d5e6f"
SYMBOL = BASE + "entity/2f6d7c1e-9d8a-4e1b-8c3a-1a2b3c4d5e6f"
DOCUMENT = BASE + "document/3f6d7c1e-9d8a-4e1b-8c3a-1a2b3c4d5e6f"
OCCURRENCE = BASE + "occurrence/4f6d7c1e-9d8a-4e1b-8c3a-1a2b3c4d5e6f"


def _text(value: str, datatype: str = "string") -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + datatype)


def _entity(identifier: str, kind: str, label: str, **extra: Any) -> NodeRecord:
    properties: dict[str, list[object]] = {
        SKOS + "prefLabel": [_text(label)],
        C1 + "lifecycle": [_text("active")],
    }
    properties.update(extra)
    return NodeRecord.model_validate(
        {"id": identifier, "types": [S + kind], "properties": properties}
    )


def _registry() -> ProfileRegistry:
    registry = ProfileRegistry()
    registry.load(ROOT / "profiles/available/software")
    return registry


def _records() -> list[NodeRecord]:
    repository = _entity(
        REPOSITORY, "CodeRepository", "ledger", **{S + "repositoryKey": [_text("ledger")]}
    )
    snapshot = _entity(
        SNAPSHOT,
        "SourceSnapshot",
        "ledger a1",
        **{S + "repositoryRef": [REPOSITORY], S + "commitId": [_text("a" * 40)]},
    )
    symbol = _entity(
        SYMBOL,
        "CodeSymbol",
        "validate",
        **{
            S + "repositoryRef": [REPOSITORY],
            S + "scipScheme": [_text("scip-python")],
            S + "packageManager": [_text("python")],
            S + "packageName": [_text("ledger")],
            S + "descriptors": [_text("ledger/api/validate().")],
        },
    )
    document = NodeRecord.model_validate(
        {
            "id": DOCUMENT,
            "types": [C1 + "Document"],
            "properties": {
                DCT + "title": [_text("ledger/api.py")],
                C1 + "sourceRevision": [_text("a" * 40)],
            },
        }
    )
    occurrence = NodeRecord.model_validate(
        {
            "id": OCCURRENCE,
            "types": [S + "SymbolOccurrence"],
            "properties": {
                S + "symbolRef": [SYMBOL],
                S + "snapshotRef": [SNAPSHOT],
                S + "fileRef": [DOCUMENT],
                S + "role": [_text("definition")],
                S + "startLine": [_text("3", "integer")],
                S + "startCharacter": [_text("4", "integer")],
                S + "endLine": [_text("3", "integer")],
                S + "endCharacter": [_text("12", "integer")],
                S + "positionEncoding": [_text("utf-8")],
            },
        }
    )
    return [repository, snapshot, symbol, document, occurrence]


def test_checked_in_profile_matches_its_generator() -> None:
    for name, content in build_files().items():
        assert (TARGET / name).read_text(encoding="utf-8") == content


def test_software_name_is_no_longer_reserved_and_loads_from_catalog() -> None:
    registry, name = load_candidate("software")
    assert name == "software"
    assert S + "SymbolOccurrence" in registry.classes


def test_software_coexists_with_topics_and_batteries() -> None:
    registry = ProfileRegistry()
    for alias in ("topics", "batteries", "software"):
        registry.load(ROOT / "profiles/available" / alias)
    assert {"topics", "batteries", "software"} <= set(registry.profiles)
    # Both extensions declare dcterms:source identically; the registry keeps one.
    assert list(registry.predicates[DCT + "source"].ranges) == [C1 + "Source"]


def test_representative_records_validate_and_map_to_storage() -> None:
    registry = _registry()
    batch = validate_records(_records(), registry)
    assert len(batch.records) == 5
    documents = records_to_documents(batch.records, registry, BASE)
    assert len(documents) == 5


def test_class_ranged_fields_are_references_with_required_classes() -> None:
    registry = _registry()
    assert reference_classes(S + "snapshotRef", registry) == frozenset({S + "SourceSnapshot"})
    assert reference_classes(S + "commitId", registry) is None
    assert reference_classes(C1 + "assertionRef", registry) == frozenset()
    occurrence = _records()[-1]
    assert set(required_class_references(occurrence, registry)) == {SYMBOL, SNAPSHOT, DOCUMENT}


def _validate(records: list[NodeRecord], known: dict[str, NodeRecord]) -> set[str]:
    changeset = ChangeSet(
        id="changeset-m08",
        author="bob",
        base_revision="revision-one",
        operations=[
            CreateOperation(record=record.model_dump(mode="json"), scope_id="scope-one")
            for record in records
        ],
        created="2026-09-29T00:00:00Z",
        updated="2026-09-29T00:00:00Z",
    )

    async def resolve(identifier: str, _revision: str) -> NodeRecord | None:
        return known.get(identifier)

    async def allow(_operation: object) -> Decision:
        return Decision(True, "allowed")

    result = asyncio.run(
        validate_changeset(
            changeset,
            registry=_registry(),
            resolve_reference=resolve,
            permission_preview=allow,
        )
    )
    return {item.code for item in result.diagnostics}


def test_reference_to_wrong_class_is_rejected_for_staged_and_existing_targets() -> None:
    repository, snapshot, symbol, document, occurrence = _records()
    assert "C1-CS-013" not in _validate([repository, snapshot, symbol, document, occurrence], {})
    wrong = occurrence.model_copy(
        update={"properties": {**occurrence.properties, S + "snapshotRef": [REPOSITORY]}}
    )
    assert "C1-CS-013" in _validate([repository, snapshot, symbol, document, wrong], {})
    # Existing targets are checked with the author's readable view.
    codes = _validate([wrong], {REPOSITORY: repository, SYMBOL: symbol, DOCUMENT: document})
    assert "C1-CS-013" in codes
    missing = _validate([occurrence], {REPOSITORY: repository, DOCUMENT: document})
    assert "C1-CS-010" in missing


def test_profile_digest_does_not_depend_on_extension_load_order() -> None:
    from c1.changes.profiles import _catalog_entries
    from c1.storage.schema import profile_digest

    entries = _catalog_entries()
    digests = set()
    for order in (("batteries", "software"), ("software", "batteries")):
        registry = ProfileRegistry()
        for alias in order:
            registry.load(entries[alias])
        digests.add(
            (
                profile_digest(registry.profiles["software"]),
                profile_digest(registry.profiles["batteries"]),
            )
        )
    standalone = (
        profile_digest(load_candidate("software")[0].profiles["software"]),
        profile_digest(load_candidate("batteries")[0].profiles["batteries"]),
    )
    assert digests == {standalone}


def test_shacl_defers_external_class_references_to_reference_validation() -> None:
    registry = _registry()
    occurrence = _records()[-1]
    # The snapshot, symbol, and file are not in this batch; SHACL cannot see their
    # types, so only ChangeSet reference validation checks them (C1-CS-010/013).
    batch = validate_records([occurrence], registry)
    assert batch.records[0].id == OCCURRENCE
    repository, snapshot, symbol, document, _ = _records()
    wrong_in_batch = occurrence.model_copy(
        update={"properties": {**occurrence.properties, S + "snapshotRef": [REPOSITORY]}}
    )
    import pytest

    from c1.model.diagnostics import ProfileError

    with pytest.raises(ProfileError):
        validate_records([repository, symbol, document, wrong_in_batch], registry)
