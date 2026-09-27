"""W3: ChangeSet validation keeps M02 rules and current authority separate."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from c1.authorization.models import Decision
from c1.changes.models import (
    ChangeOperation,
    ChangeSet,
    CreateOperation,
    InstallProfileOperation,
    ReplaceOperation,
)
from c1.changes.validation import validate_changeset
from c1.model.diagnostics import Diagnostic
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry, PropertyDefinition
from c1.model.records import AssertionRecord, EntityRecord, EvidenceRecord, SourceRecord
from c1.model.time import TimeBoundary, TimeInterval

BASE = "urn:c1:instance:dev:"
C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ENTITY = BASE + "entity/one"
SOURCE = BASE + "source/one"
EVIDENCE = BASE + "evidence/one"
VEHICLE = "urn:c1:ns:example-vehicle#"


def _literal(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + "string")


def _entity() -> NodeRecord:
    return EntityRecord(id=ENTITY, labels=[_literal("Ada")]).to_node()


def _assertion(
    name: str = "one",
    *,
    evidence: list[str] | None = None,
    manual: bool = True,
    attributed: str | None = BASE + "agent/bob",
    origin: str = "manual",
    valid_interval: str | None = None,
    value: str = "1",
) -> NodeRecord:
    return AssertionRecord(
        id=BASE + "assertion/" + name,
        subject=ENTITY,
        predicate=C1 + "revenue",
        object=LiteralValue(lexical=value, datatype=XSD + "decimal"),
        origin=origin,  # type: ignore[arg-type]
        evidence_ids=evidence or [],
        manual_statement=manual,
        attributed_to=attributed,
        valid_interval=valid_interval,
    ).to_node()


def _change(*records: NodeRecord, restore: str | None = None) -> ChangeSet:
    operations: list[ChangeOperation] = [
        CreateOperation(record=record.model_dump(mode="json"), scope_id="scope-one")
        for record in records
    ]
    return ChangeSet(
        id="changeset-one",
        author="bob",
        base_revision="revision-one",
        operations=operations,
        restores_from_revision=restore,
        created="2026-09-27T00:00:00Z",
        updated="2026-09-27T00:00:00Z",
    )


async def _allow(_operation: object) -> Decision:
    return Decision(True, "allowed")


def test_source_backed_and_attributed_manual_records_validate_together() -> None:
    async def case() -> None:
        source = SourceRecord(id=SOURCE, title=_literal("Report"), kind="report").to_node()
        evidence = EvidenceRecord(
            id=EVIDENCE,
            assertion_id=BASE + "assertion/backed",
            source_id=SOURCE,
            source_revision="v1",
        ).to_node()
        backed = _assertion("backed", evidence=[EVIDENCE], manual=False)
        manual = _assertion("manual")

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        result = await validate_changeset(
            _change(_entity(), source, evidence, backed, manual),
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
        )
        assert result.accepted
        assert len(result.records) == 5
        assert not result.diagnostics

    asyncio.run(case())


def test_absent_and_unreadable_reference_have_identical_diagnostics() -> None:
    async def case() -> None:
        claim = _assertion()

        async def absent(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        async def unreadable(_identifier: str, _revision: str) -> NodeRecord | None:
            # The caller's authority-gated resolver intentionally returns None.
            return None

        absent_result = await validate_changeset(
            _change(claim),
            registry=ProfileRegistry(),
            resolve_reference=absent,
            permission_preview=_allow,
        )
        hidden_result = await validate_changeset(
            _change(claim),
            registry=ProfileRegistry(),
            resolve_reference=unreadable,
            permission_preview=_allow,
        )
        assert absent_result.diagnostics == hidden_result.diagnostics
        assert [item.code for item in hidden_result.diagnostics] == ["C1-CS-010"]

    asyncio.run(case())


def test_manual_and_imported_attribution_rules() -> None:
    async def case() -> None:
        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return _entity()

        missing_manual = _assertion(manual=False, attributed=None)
        imported = _assertion("imported", origin="imported")
        result = await validate_changeset(
            _change(missing_manual, imported),
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
        )
        assert sum(item.code == "C1-CS-011" for item in result.diagnostics) == 2
        assert not result.accepted

    asyncio.run(case())


def test_restore_requires_exact_old_content_and_replace_only() -> None:
    async def case() -> None:
        original = _entity()
        changed = EntityRecord(id=ENTITY, labels=[_literal("Grace")]).to_node()

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return original

        async def restore(_identifier: str, _revision: str) -> NodeRecord | None:
            return original

        proposal = _change(changed).model_copy(
            update={
                "operations": [
                    ReplaceOperation(
                        resource_id=ENTITY,
                        record=changed.model_dump(mode="json"),
                        reason="restore",
                    )
                ],
                "restores_from_revision": "old-revision",
            }
        )
        result = await validate_changeset(
            proposal,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
            restore_record=restore,
        )
        assert any(item.code == "C1-CS-030" for item in result.diagnostics)
        exact = proposal.model_copy(
            update={
                "operations": [
                    ReplaceOperation(
                        resource_id=ENTITY,
                        record=original.model_dump(mode="json"),
                        reason="restore",
                    )
                ]
            }
        )
        accepted = await validate_changeset(
            exact,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
            restore_record=restore,
        )
        assert accepted.accepted

    asyncio.run(case())


def test_declared_single_value_conflict_is_informational_only() -> None:
    async def case() -> None:
        registry = ProfileRegistry()
        revenue = registry.predicates[C1 + "revenue"]
        registry.predicates[C1 + "revenue"] = PropertyDefinition(
            revenue.name,
            revenue.ranges,
            revenue.min_count,
            1,
            revenue.enum,
        )
        first = _assertion("first", value="1")
        second = _assertion("second", value="2")
        interval = TimeInterval(
            start=TimeBoundary(state="known", lexical="2020-01-01Z", datatype=XSD + "date"),
            end=TimeBoundary(state="known", lexical="2021-01-01Z", datatype=XSD + "date"),
        )

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return _entity()

        async def existing(_subject: str, _predicate: str, _revision: str) -> Sequence[NodeRecord]:
            return []

        async def dates(
            _assertion: NodeRecord,
            _staged: dict[str, NodeRecord],
            _revision: str,
        ) -> TimeInterval | None:
            return interval

        result = await validate_changeset(
            _change(first, second),
            registry=registry,
            resolve_reference=reference,
            permission_preview=_allow,
            existing_assertions=existing,
            interval_for_assertion=dates,
        )
        assert result.accepted
        assert [item.code for item in result.diagnostics] == ["C1-CS-020"]

    asyncio.run(case())


def test_subject_class_cardinality_flags_vehicle_claims_without_leaking_hidden_subject() -> None:
    async def case() -> None:
        registry = ProfileRegistry()
        registry.load(Path(__file__).resolve().parents[3] / "profiles/available/example-vehicle")
        assert registry.predicates[VEHICLE + "wheelCount"].max_count is None
        vehicle = NodeRecord(
            id=BASE + "entity/vehicle",
            types=[VEHICLE + "Vehicle"],
            properties={
                "http://www.w3.org/2004/02/skos/core#prefLabel": [_literal("Car")],
                C1 + "lifecycle": [_literal("active")],
                VEHICLE + "wheelCount": [LiteralValue(lexical="4", datatype=XSD + "integer")],
            },
        )
        claims = [
            AssertionRecord(
                id=BASE + f"assertion/vehicle-{count}",
                subject=vehicle.id,
                predicate=VEHICLE + "wheelCount",
                object=LiteralValue(lexical=str(count), datatype=XSD + "integer"),
                origin="manual",
                manual_statement=True,
                attributed_to=BASE + "agent/bob",
            ).to_node()
            for count in (4, 5)
        ]
        interval = TimeInterval(
            start=TimeBoundary(state="known", lexical="2020-01-01Z", datatype=XSD + "date"),
            end=TimeBoundary(state="known", lexical="2021-01-01Z", datatype=XSD + "date"),
        )

        async def visible(_identifier: str, _revision: str) -> NodeRecord | None:
            return vehicle

        async def hidden(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        async def dates(
            _assertion: NodeRecord,
            _staged: dict[str, NodeRecord],
            _revision: str,
        ) -> TimeInterval | None:
            return interval

        for proposal, resolver in (
            (_change(vehicle, *claims), hidden),
            (_change(*claims), visible),
        ):
            result = await validate_changeset(
                proposal,
                registry=registry,
                resolve_reference=resolver,
                permission_preview=_allow,
                interval_for_assertion=dates,
            )
            assert result.accepted
            assert [item.code for item in result.diagnostics] == ["C1-CS-020"]

        inaccessible = await validate_changeset(
            _change(*claims),
            registry=registry,
            resolve_reference=hidden,
            permission_preview=_allow,
            interval_for_assertion=dates,
        )
        assert not inaccessible.accepted
        assert [item.code for item in inaccessible.diagnostics] == ["C1-CS-010", "C1-CS-010"]

    asyncio.run(case())


def test_permission_preview_uses_reason_codes_and_rejects_whole_change() -> None:
    async def case() -> None:
        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        async def permission(operation: object) -> Decision:
            assert isinstance(operation, CreateOperation)
            return Decision(operation.scope_id == "scope-one", "inactive_scope")

        proposal = _change(_entity()).model_copy(
            update={
                "operations": [
                    CreateOperation(record=_entity().model_dump(mode="json"), scope_id="scope-two")
                ]
            }
        )
        result = await validate_changeset(
            proposal,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=permission,
        )
        assert not result.accepted
        assert [(item.allowed, item.reason) for item in result.permission_preview] == [
            (False, "permission_denied")
        ]

    asyncio.run(case())


def test_m02_diagnostics_cover_each_invalid_record() -> None:
    async def case() -> None:
        invalid_one = NodeRecord(id=BASE + "entity/bad-one", types=[C1 + "Entity"], properties={})
        invalid_two = NodeRecord(id=BASE + "entity/bad-two", types=[C1 + "Entity"], properties={})

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        result = await validate_changeset(
            _change(invalid_one, invalid_two),
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
        )
        assert [item.code for item in result.diagnostics] == ["C1-IX-030", "C1-IX-030"]
        assert not result.accepted

    asyncio.run(case())


def test_missing_id_is_minted_and_returned_in_normalized_payload() -> None:
    async def case() -> None:
        raw = _entity().model_dump(mode="json")
        del raw["id"]
        change = _change(_entity()).model_copy(
            update={"operations": [CreateOperation(record=raw, scope_id="scope-one")]}
        )

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        minted = BASE + "entity/minted"
        result = await validate_changeset(
            change,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
            mint_identifier=lambda _index, _record: minted,
        )
        assert result.accepted
        assert result.minted_ids == {0: minted}
        operation = result.normalized_operations[0]
        assert isinstance(operation, CreateOperation)
        assert operation.record["id"] == minted
        assert result.records[0].id == minted

    asyncio.run(case())


def test_incompatible_profile_diagnostic_rejects_installation() -> None:
    async def case() -> None:
        change = _change(_entity()).model_copy(
            update={"operations": [InstallProfileOperation(profile="example-vehicle-v2")]}
        )

        async def reference(_identifier: str, _revision: str) -> NodeRecord | None:
            return None

        async def profile(_name: str) -> list[Diagnostic]:
            return [
                Diagnostic(
                    code="C1-PR-004",
                    severity="error",
                    path="/profile",
                    message="MigrationRequired",
                )
            ]

        result = await validate_changeset(
            change,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=_allow,
            validate_profile=profile,
        )
        assert not result.accepted
        assert [item.code for item in result.diagnostics] == ["C1-PR-004"]
        assert result.records == ()

    asyncio.run(case())
