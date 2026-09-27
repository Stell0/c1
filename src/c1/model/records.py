"""Typed, transport-independent records for the supported core profile.

Each record keeps its canonical IRI.  ``to_node`` maps fields to the versioned
vocabulary; storage IDs and authorization bindings are separate concerns.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from c1.model.ids import validate_iri
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord

C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCTERMS = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
OA = "http://www.w3.org/ns/oa#"


def _text(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD_STRING)


def _properties(
    *,
    iris: dict[str, str | None] | None = None,
    iri_sets: dict[str, list[str]] | None = None,
    literals: dict[str, LiteralValue | None] | None = None,
    literal_sets: dict[str, list[LiteralValue]] | None = None,
    texts: dict[str, str | None] | None = None,
) -> dict[str, list[str | LiteralValue]]:
    result: dict[str, list[str | LiteralValue]] = {}
    for predicate, iri in (iris or {}).items():
        if iri is not None:
            result[predicate] = [iri]
    for predicate, iri_values in (iri_sets or {}).items():
        if iri_values:
            result[predicate] = list(iri_values)
    for predicate, literal in (literals or {}).items():
        if literal is not None:
            result[predicate] = [literal]
    for predicate, literal_values in (literal_sets or {}).items():
        if literal_values:
            result[predicate] = list(literal_values)
    for predicate, text in (texts or {}).items():
        if text is not None:
            result[predicate] = [_text(text)]
    return result


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return validate_iri(value)

    def to_node(self) -> NodeRecord:
        raise NotImplementedError


class EntityRecord(_Record):
    types: list[str] = Field(default_factory=lambda: [C1 + "Entity"])
    labels: list[LiteralValue] = Field(min_length=1)
    description: LiteralValue | None = None
    aliases: list[LiteralValue] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    lifecycle: Literal["active", "superseded", "retracted"] = "active"
    project_references: list[str] = Field(default_factory=list)
    provisioned_scope_hint: str | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=self.types,
            properties=_properties(
                iris={C1 + "provisionedScopeHint": self.provisioned_scope_hint},
                iri_sets={
                    C1 + "keyword": self.keywords,
                    C1 + "projectReference": self.project_references,
                },
                literals={DCTERMS + "description": self.description},
                literal_sets={SKOS + "prefLabel": self.labels, SKOS + "altLabel": self.aliases},
                texts={C1 + "lifecycle": self.lifecycle},
            ),
        )

    @classmethod
    def from_node(cls, node: NodeRecord) -> Self:
        def literal_values(predicate: str) -> list[LiteralValue]:
            return [
                value
                for value in node.properties.get(predicate, [])
                if isinstance(value, LiteralValue)
            ]

        def iri_values(predicate: str) -> list[str]:
            return [value for value in node.properties.get(predicate, []) if isinstance(value, str)]

        description = literal_values(DCTERMS + "description")
        scope = iri_values(C1 + "provisionedScopeHint")
        lifecycle = literal_values(C1 + "lifecycle")
        return cls(
            id=node.id,
            types=node.types,
            labels=literal_values(SKOS + "prefLabel"),
            description=description[0] if description else None,
            aliases=literal_values(SKOS + "altLabel"),
            keywords=iri_values(C1 + "keyword"),
            lifecycle=lifecycle[0].lexical if lifecycle else "active",  # type: ignore[arg-type]
            project_references=iri_values(C1 + "projectReference"),
            provisioned_scope_hint=scope[0] if scope else None,
        )


class AssertionRecord(_Record):
    subject: str
    predicate: str
    object: str | LiteralValue
    origin: Literal["manual", "imported", "derived"]
    review_state: Literal["reported", "confirmed", "disputed"] = "reported"
    lifecycle: Literal["active", "superseded", "retracted"] = "active"
    valid_interval: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    activity_id: str | None = None
    manual_statement: bool = False
    attributed_to: str | None = None
    confidence: LiteralValue | None = None
    confidence_method: str | None = None
    provisioned_scope_hint: str | None = None

    def to_node(self) -> NodeRecord:
        properties = _properties(
            iris={
                RDF + "subject": self.subject,
                RDF + "predicate": self.predicate,
                C1 + "validDuring": self.valid_interval,
                PROV + "wasGeneratedBy": self.activity_id,
                PROV + "wasAttributedTo": self.attributed_to,
                C1 + "provisionedScopeHint": self.provisioned_scope_hint,
            },
            iri_sets={C1 + "evidence": self.evidence_ids},
            literals={C1 + "confidence": self.confidence},
            texts={
                C1 + "origin": self.origin,
                C1 + "reviewState": self.review_state,
                C1 + "lifecycle": self.lifecycle,
                C1 + "confidenceMethod": self.confidence_method,
            },
        )
        properties[RDF + "object"] = [self.object]
        properties[C1 + "manualStatement"] = [
            LiteralValue(
                lexical="true" if self.manual_statement else "false",
                datatype="http://www.w3.org/2001/XMLSchema#boolean",
            )
        ]
        return NodeRecord(id=self.id, types=[C1 + "Assertion"], properties=properties)


class SourceRecord(_Record):
    title: LiteralValue
    kind: str
    locator: LiteralValue | None = None
    revision: str | None = None
    digest: str | None = None
    issued: LiteralValue | None = None
    observed_at: LiteralValue | None = None
    creator: str | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "Source"],
            properties=_properties(
                iris={DCTERMS + "creator": self.creator},
                literals={
                    DCTERMS + "title": self.title,
                    DCTERMS + "identifier": self.locator,
                    DCTERMS + "issued": self.issued,
                    C1 + "observedAt": self.observed_at,
                },
                texts={
                    C1 + "sourceKind": self.kind,
                    C1 + "sourceRevision": self.revision,
                    C1 + "contentDigest": self.digest,
                },
            ),
        )


class EvidenceRecord(_Record):
    assertion_id: str
    source_id: str
    source_revision: str
    selector_id: str | None = None
    excerpt: LiteralValue | None = None
    observed_at: LiteralValue | None = None
    activity_id: str | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "Evidence"],
            properties=_properties(
                iris={
                    C1 + "assertionRef": self.assertion_id,
                    OA + "hasSource": self.source_id,
                    OA + "hasSelector": self.selector_id,
                    PROV + "wasGeneratedBy": self.activity_id,
                },
                literals={C1 + "excerpt": self.excerpt, C1 + "observedAt": self.observed_at},
                texts={C1 + "sourceRevision": self.source_revision},
            ),
        )


class ActivityRecord(_Record):
    actor: str
    used: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    outcome: str | None = None
    result_revision: str | None = None
    tool_name: str | None = None
    tool_version: str | None = None
    method: str | None = None
    started_at: LiteralValue | None = None
    ended_at: LiteralValue | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[PROV + "Activity"],
            properties=_properties(
                iris={PROV + "wasAttributedTo": self.actor},
                iri_sets={PROV + "used": self.used, C1 + "output": self.outputs},
                literals={
                    PROV + "startedAtTime": self.started_at,
                    PROV + "endedAtTime": self.ended_at,
                },
                texts={
                    C1 + "toolName": self.tool_name,
                    C1 + "toolVersion": self.tool_version,
                    C1 + "method": self.method,
                    C1 + "outcome": self.outcome,
                    C1 + "resultRevision": self.result_revision,
                },
            ),
        )


class ResolutionRecord(_Record):
    candidates: list[str] = Field(min_length=1)
    decision: str
    actor: str
    rationale: str

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "ResolutionRecord"],
            properties=_properties(
                iris={PROV + "wasAttributedTo": self.actor},
                iri_sets={C1 + "candidate": self.candidates},
                texts={C1 + "decision": self.decision, C1 + "rationale": self.rationale},
            ),
        )


class DocumentRecord(_Record):
    title: LiteralValue
    source_revision: str | None = None
    digest: str | None = None
    issued: LiteralValue | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "Document"],
            properties=_properties(
                literals={DCTERMS + "title": self.title, DCTERMS + "issued": self.issued},
                texts={
                    C1 + "sourceRevision": self.source_revision,
                    C1 + "contentDigest": self.digest,
                },
            ),
        )


class DocumentPartRecord(_Record):
    document_id: str
    order_key: str
    text: str | None = None
    title: LiteralValue | None = None
    kind: str | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "DocumentPart"],
            properties=_properties(
                iris={C1 + "partOfDocument": self.document_id},
                literals={DCTERMS + "title": self.title},
                texts={
                    C1 + "orderKey": self.order_key,
                    C1 + "text": self.text,
                    C1 + "partKind": self.kind,
                },
            ),
        )


class SchemaProfileRecord(_Record):
    name: str
    version: str

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "SchemaProfile"],
            properties=_properties(
                texts={C1 + "profileName": self.name, C1 + "profileVersion": self.version}
            ),
        )


class ChangeSetRecord(_Record):
    base_revision: str
    profile_version: str
    status: str
    request_digest: str
    proposed_operations: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    target_resource_ids: list[str] = Field(default_factory=list)
    intended_creation_scopes: list[str] = Field(default_factory=list)
    validation_report_id: str | None = None
    review_decision_id: str | None = None
    apply_receipt_id: str | None = None

    def to_node(self) -> NodeRecord:
        properties = _properties(
            iris={
                C1 + "validationReport": self.validation_report_id,
                C1 + "reviewDecision": self.review_decision_id,
                C1 + "applyReceipt": self.apply_receipt_id,
            },
            texts={
                C1 + "baseRevision": self.base_revision,
                C1 + "profileVersion": self.profile_version,
                C1 + "status": self.status,
                C1 + "requestDigest": self.request_digest,
            },
        )
        properties[C1 + "proposedOperation"] = [_text(value) for value in self.proposed_operations]
        properties.update(
            _properties(
                iri_sets={
                    C1 + "proposedEvidence": self.evidence_ids,
                    C1 + "targetResource": self.target_resource_ids,
                    C1 + "intendedCreationScope": self.intended_creation_scopes,
                }
            )
        )
        return NodeRecord(id=self.id, types=[C1 + "ChangeSet"], properties=properties)


class ValidationReport(_Record):
    changeset_id: str
    status: str
    request_digest: str
    diagnostics: list[str] = Field(default_factory=list)

    def to_node(self) -> NodeRecord:
        properties = _properties(
            iris={C1 + "changeSet": self.changeset_id},
            texts={C1 + "status": self.status, C1 + "requestDigest": self.request_digest},
        )
        if self.diagnostics:
            properties[C1 + "diagnostic"] = [_text(value) for value in self.diagnostics]
        return NodeRecord(
            id=self.id,
            types=[C1 + "ValidationReport"],
            properties=properties,
        )


class ReviewDecision(_Record):
    changeset_id: str
    decision: str
    actor: str
    rationale: str | None = None

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "ReviewDecision"],
            properties=_properties(
                iris={C1 + "changeSet": self.changeset_id, PROV + "wasAttributedTo": self.actor},
                texts={C1 + "decision": self.decision, C1 + "rationale": self.rationale},
            ),
        )


class ApplyReceipt(_Record):
    changeset_id: str
    knowledge_commit: str
    request_digest: str

    def to_node(self) -> NodeRecord:
        return NodeRecord(
            id=self.id,
            types=[C1 + "ApplyReceipt"],
            properties=_properties(
                iris={C1 + "changeSet": self.changeset_id},
                texts={
                    C1 + "knowledgeCommit": self.knowledge_commit,
                    C1 + "requestDigest": self.request_digest,
                },
            ),
        )
