"""M02-D2/T04: typed records retain identity and suggest only visible duplicates."""

from __future__ import annotations

from c1.interchange import duplicate_candidates, validate_records
from c1.model.literals import LiteralValue
from c1.model.records import (
    ActivityRecord,
    ApplyReceipt,
    AssertionRecord,
    ChangeSetRecord,
    DocumentPartRecord,
    DocumentRecord,
    EntityRecord,
    EvidenceRecord,
    ResolutionRecord,
    ReviewDecision,
    SchemaProfileRecord,
    SourceRecord,
    ValidationReport,
)

BASE = "urn:c1:instance:dev:"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def test_entity_changes_do_not_change_canonical_identity() -> None:
    first = EntityRecord(
        id=BASE + "entity/00000000-0000-4000-8000-000000000001",
        labels=[LiteralValue(lexical="Ada", datatype=RDF + "langString", language="en")],
    )
    changed = first.model_copy(
        update={
            "labels": [
                LiteralValue(lexical="Ada Example", datatype=RDF + "langString", language="en")
            ],
            "project_references": [BASE + "project/one"],
            "provisioned_scope_hint": BASE + "scope/old",
        }
    )
    assert first.to_node().id == changed.to_node().id
    validated = validate_records([changed.to_node()])
    assert EntityRecord.from_node(validated.records[0]).id == first.id


def test_duplicate_candidate_uses_only_visible_entities() -> None:
    label = LiteralValue(lexical="Ada", datatype=XSD + "string")
    one = EntityRecord(id=BASE + "entity/one", labels=[label]).to_node()
    two = EntityRecord(id=BASE + "entity/two", labels=[label]).to_node()
    hidden = EntityRecord(id=BASE + "entity/hidden", labels=[label]).to_node()
    diagnostics = duplicate_candidates([two], visible_existing=[one])
    assert [(item.code, item.severity) for item in diagnostics] == [("C1-IX-040", "info")]
    assert one.id in diagnostics[0].message
    assert duplicate_candidates([two], visible_existing=[]) == []
    assert hidden.id not in diagnostics[0].message
    assert [item.code for item in validate_records([one, two]).diagnostics] == ["C1-IX-040"]


def test_duplicate_candidate_handles_mixed_language_labels() -> None:
    labels = [
        LiteralValue(lexical="Ada", datatype=XSD + "string"),
        LiteralValue(lexical="Ada", datatype=RDF + "langString", language="en"),
    ]
    one = EntityRecord(id=BASE + "entity/one", labels=labels).to_node()
    two = EntityRecord(id=BASE + "entity/two", labels=labels).to_node()
    assert [item.code for item in duplicate_candidates([one, two])] == ["C1-IX-040"]


def test_named_record_fields_survive_to_node_mapping() -> None:
    text = LiteralValue(lexical="title", datatype=XSD + "string")
    models = [
        (
            SourceRecord(
                id=BASE + "source/one",
                title=text,
                kind="page",
                locator=text,
                revision="r1",
                digest="sha256:abc",
                issued=LiteralValue(lexical="2020-01-01", datatype=XSD + "date"),
                observed_at=LiteralValue(
                    lexical="2020-01-01T00:00:00Z", datatype=XSD + "dateTimeStamp"
                ),
                creator=BASE + "agent/one",
            ),
            8,
        ),
        (
            EvidenceRecord(
                id=BASE + "evidence/one",
                assertion_id=BASE + "assertion/one",
                source_id=BASE + "source/one",
                source_revision="r1",
                selector_id=BASE + "selector/one",
                excerpt=text,
                observed_at=LiteralValue(
                    lexical="2020-01-01T00:00:00Z", datatype=XSD + "dateTimeStamp"
                ),
                activity_id=BASE + "activity/one",
            ),
            7,
        ),
        (
            ActivityRecord(
                id=BASE + "activity/one",
                actor=BASE + "agent/one",
                used=[BASE + "source/one"],
                outputs=[BASE + "assertion/one"],
                outcome="complete",
                result_revision="r1",
                tool_name="fixture-client",
                tool_version="1",
                method="manual import",
                started_at=LiteralValue(
                    lexical="2020-01-01T00:00:00Z", datatype=XSD + "dateTimeStamp"
                ),
                ended_at=LiteralValue(
                    lexical="2020-01-01T00:00:01Z", datatype=XSD + "dateTimeStamp"
                ),
            ),
            10,
        ),
        (
            ResolutionRecord(
                id=BASE + "resolution/one",
                candidates=[BASE + "entity/one"],
                decision="ambiguous",
                actor=BASE + "agent/one",
                rationale="Review later",
            ),
            4,
        ),
        (
            DocumentRecord(
                id=BASE + "document/one",
                title=text,
                source_revision="r1",
                digest="sha256:abc",
                issued=LiteralValue(lexical="2020-01-01", datatype=XSD + "date"),
            ),
            4,
        ),
        (
            DocumentPartRecord(
                id=BASE + "part/one",
                document_id=BASE + "document/one",
                order_key="001",
                text="body",
                title=text,
                kind="section",
            ),
            5,
        ),
        (SchemaProfileRecord(id=BASE + "profile/core", name="core", version="1.0.0"), 2),
        (
            ChangeSetRecord(
                id=BASE + "changeset/one",
                base_revision="r0",
                profile_version="1.0.0",
                status="draft",
                request_digest="sha256:abc",
                proposed_operations=["insert entity"],
                evidence_ids=[BASE + "evidence/one"],
                target_resource_ids=[BASE + "entity/one"],
                intended_creation_scopes=[BASE + "scope/one"],
                validation_report_id=BASE + "validation/one",
                review_decision_id=BASE + "review/one",
                apply_receipt_id=BASE + "receipt/one",
            ),
            11,
        ),
        (
            ValidationReport(
                id=BASE + "validation/one",
                changeset_id=BASE + "changeset/one",
                status="passed",
                request_digest="sha256:abc",
                diagnostics=["none"],
            ),
            4,
        ),
        (
            ReviewDecision(
                id=BASE + "review/one",
                changeset_id=BASE + "changeset/one",
                decision="approve",
                actor=BASE + "agent/one",
                rationale="evidence checked",
            ),
            4,
        ),
        (
            ApplyReceipt(
                id=BASE + "receipt/one",
                changeset_id=BASE + "changeset/one",
                knowledge_commit="branch:abc",
                request_digest="sha256:abc",
            ),
            3,
        ),
    ]
    for model, expected_predicates in models:
        node = model.to_node()
        assert node.id == model.id
        assert len(node.properties) == expected_predicates
        assert len(validate_records([node]).records) == 1


def test_assertion_model_retains_all_qualifiers() -> None:
    model = AssertionRecord(
        id=BASE + "assertion/one",
        subject=BASE + "entity/one",
        predicate="urn:c1:ns:core#revenue",
        object=LiteralValue(lexical="42.5000", datatype=XSD + "decimal"),
        origin="manual",
        review_state="reported",
        lifecycle="active",
        valid_interval=BASE + "interval/one",
        evidence_ids=[BASE + "evidence/one"],
        activity_id=BASE + "activity/one",
        manual_statement=True,
        attributed_to=BASE + "agent/one",
        confidence=LiteralValue(lexical="0.70", datatype=XSD + "decimal"),
        confidence_method="expert judgement",
        provisioned_scope_hint=BASE + "scope/old",
    )
    node = model.to_node()
    assert len(node.properties) == 14
    assert len(validate_records([node]).records) == 1
