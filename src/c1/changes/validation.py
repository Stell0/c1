"""Pure ChangeSet validation with injected revision and authority lookups.

Resolvers are supplied by the authenticated service. In particular,
``resolve_reference`` must return ``None`` for both absent and unreadable
resources and must authorize against current bindings before reading a base
revision. This module never reads the backend or guesses a permission.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from c1.authorization.models import Decision
from c1.changes.models import (
    ChangeOperation,
    ChangeSet,
    InstallProfileOperation,
    ReplaceOperation,
)
from c1.interchange import validate_records
from c1.model.diagnostics import Diagnostic, ProfileError
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.time import TimeInterval

C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PROV = "http://www.w3.org/ns/prov#"
OA = "http://www.w3.org/ns/oa#"
TIME = "http://www.w3.org/2006/time#"

# These properties point to C1 knowledge resources. The claim predicate,
# provenance actor, project/scope hints, and literal URI locators are not
# references resolved against the knowledge repository.
_REFERENCE_PROPERTIES = frozenset(
    {
        RDF + "subject",
        RDF + "object",
        C1 + "validDuring",
        C1 + "evidence",
        C1 + "assertionRef",
        C1 + "partOfDocument",
        C1 + "candidate",
        C1 + "keyword",
        OA + "hasSource",
        OA + "hasSelector",
        PROV + "wasGeneratedBy",
        PROV + "used",
        C1 + "output",
        TIME + "hasBeginning",
        TIME + "hasEnd",
    }
)

ReferenceResolver = Callable[[str, str], Awaitable[NodeRecord | None]]
PermissionPreviewer = Callable[[ChangeOperation], Awaitable[Decision]]
RestoreResolver = Callable[[str, str], Awaitable[NodeRecord | None]]
ExistingAssertions = Callable[[str, str, str], Awaitable[Sequence[NodeRecord]]]
IntervalResolver = Callable[
    [NodeRecord, dict[str, NodeRecord], str], Awaitable[TimeInterval | None]
]
ProfileValidator = Callable[[str], Awaitable[Sequence[Diagnostic]]]
IdentifierMinter = Callable[[int, NodeRecord], str]


@dataclass(frozen=True)
class OperationPreview:
    index: int
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ValidationResult:
    diagnostics: tuple[Diagnostic, ...]
    permission_preview: tuple[OperationPreview, ...]
    records: tuple[NodeRecord, ...]
    normalized_operations: tuple[ChangeOperation, ...]
    minted_ids: dict[int, str]

    @property
    def accepted(self) -> bool:
        return all(item.severity != "error" for item in self.diagnostics) and all(
            item.allowed for item in self.permission_preview
        )


def _diagnostic(code: str, severity: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=severity, path=path, message=message)  # type: ignore[arg-type]


def _first_iri(record: NodeRecord, predicate: str) -> str | None:
    values = record.properties.get(predicate, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def _text(record: NodeRecord, predicate: str) -> str | None:
    values = record.properties.get(predicate, [])
    return values[0].lexical if len(values) == 1 and isinstance(values[0], LiteralValue) else None


def _manual_rule(record: NodeRecord, path: str) -> list[Diagnostic]:
    if C1 + "Assertion" not in record.types:
        return []
    evidence = record.properties.get(C1 + "evidence", [])
    activity = _first_iri(record, PROV + "wasGeneratedBy")
    attributed = _first_iri(record, PROV + "wasAttributedTo")
    manual = _text(record, C1 + "manualStatement") in {"true", "1"}
    origin = _text(record, C1 + "origin")
    if (not evidence and (not manual or not attributed)) or (
        origin in {"imported", "derived"} and not evidence and not activity
    ):
        return [
            _diagnostic(
                "C1-CS-011",
                "error",
                path,
                "Assertion needs evidence or an attributed manual statement; "
                "imported and derived assertions also need evidence or an activity",
            )
        ]
    return []


def _known_overlap(left: TimeInterval | None, right: TimeInterval | None) -> bool:
    if left is None or right is None or left.timezone_unknown or right.timezone_unknown:
        return False
    if any(
        boundary.state == "unknown" for boundary in (left.start, left.end, right.start, right.end)
    ):
        return False
    left_start, left_end = left.start_earliest, left.end_latest
    right_start, right_end = right.start_earliest, right.end_latest
    assert left_start is not None and left_end is not None
    assert right_start is not None and right_end is not None
    return left_start < right_end and right_start < left_end


def _single_valued_for_subject(
    registry: ProfileRegistry, subject: NodeRecord, predicate: str
) -> bool:
    declared = registry.predicates.get(predicate)
    if declared is None:
        return False
    if declared.max_count == 1:
        return True
    try:
        subject_class = registry.primary_class(subject.types)
    except ProfileError:
        return False
    property_definition = subject_class.properties.get(predicate)
    return property_definition is not None and property_definition.max_count == 1


async def validate_changeset(
    changeset: ChangeSet,
    *,
    registry: ProfileRegistry,
    resolve_reference: ReferenceResolver,
    permission_preview: PermissionPreviewer,
    restore_record: RestoreResolver | None = None,
    existing_assertions: ExistingAssertions | None = None,
    interval_for_assertion: IntervalResolver | None = None,
    validate_profile: ProfileValidator | None = None,
    mint_identifier: IdentifierMinter | None = None,
) -> ValidationResult:
    """Validate each operation without publishing knowledge or permissions.

    A caller must persist returned ``normalized_operations`` before review so
    minted identifiers and their digest remain stable through apply. The
    callbacks must use ``changeset.base_revision`` and current authorization.
    Existing-assertion queries must return only assertions readable by the
    author; conflict flags must not disclose protected claims.
    """

    diagnostics: list[Diagnostic] = []
    previews: list[OperationPreview] = []
    parsed: list[tuple[int, NodeRecord]] = []
    normalized: list[ChangeOperation] = []
    minted: dict[int, str] = {}

    for index, operation in enumerate(changeset.operations):
        path = f"/operations/{index}"
        try:
            decision = await permission_preview(operation)
        except Exception:
            decision = Decision(False, "security_unavailable")
        # A missing target and a protected target must have the same public
        # denial. The caller may retain the internal Decision for audit.
        previews.append(
            OperationPreview(
                index, decision.allowed, "allowed" if decision.allowed else "permission_denied"
            )
        )

        if isinstance(operation, InstallProfileOperation):
            normalized.append(operation)
            if validate_profile is None:
                diagnostics.append(
                    _diagnostic("C1-PR-004", "error", path, "Profile validation unavailable")
                )
            else:
                try:
                    diagnostics.extend(await validate_profile(operation.profile))
                except ProfileError as exc:
                    diagnostics.extend(exc.diagnostics)
            continue

        raw: dict[str, Any] = dict(operation.record)
        if not raw.get("id") and mint_identifier is not None:
            try:
                provisional = NodeRecord.model_validate({**raw, "id": "urn:c1:pending:mint"})
                minted_id = mint_identifier(index, provisional)
                raw["id"] = minted_id
                minted[index] = minted_id
            except (ProfileError, ValidationError, ValueError):
                pass
        try:
            record = NodeRecord.model_validate(raw)
        except ValidationError:
            diagnostics.append(
                _diagnostic("C1-IX-030", "error", path + "/record", "Invalid M02 record")
            )
            normalized.append(operation)
            continue
        if isinstance(operation, ReplaceOperation) and record.id != operation.resource_id:
            diagnostics.append(
                _diagnostic(
                    "C1-CS-030", "error", path + "/record/id", "Replacement ID differs from target"
                )
            )
        normalized.append(operation.model_copy(update={"record": record.model_dump(mode="json")}))
        parsed.append((index, record))

    staged = {record.id: record for _, record in parsed}
    visible_references: dict[str, NodeRecord | None] = {}
    if len(staged) != len(parsed):
        diagnostics.append(
            _diagnostic("C1-IX-030", "error", "/operations", "Duplicate record identifier")
        )
    validated: list[NodeRecord] = []
    for index, record in parsed:
        path = f"/operations/{index}/record"
        try:
            batch = validate_records([record], registry)
            canonical_record = batch.records[0]
            validated.append(canonical_record)
            operation = normalized[index]
            normalized[index] = operation.model_copy(
                update={"record": canonical_record.model_dump(mode="json")}
            )
            diagnostics.extend(batch.diagnostics)
        except ProfileError as exc:
            diagnostics.extend(exc.diagnostics)
        diagnostics.extend(_manual_rule(record, path))

        operation = normalized[index]
        if isinstance(operation, ReplaceOperation) and changeset.restores_from_revision:
            old: NodeRecord | None = None
            if restore_record is not None:
                try:
                    old = await restore_record(
                        operation.resource_id, changeset.restores_from_revision
                    )
                except Exception:
                    pass
            if (
                old is None
                or old.id != record.id
                or set(old.types) != set(record.types)
                or {key: frozenset(values) for key, values in old.properties.items() if values}
                != {key: frozenset(values) for key, values in record.properties.items() if values}
            ):
                diagnostics.append(
                    _diagnostic(
                        "C1-CS-030", "error", path, "Record does not equal claimed restore revision"
                    )
                )

        for predicate, values in record.properties.items():
            if predicate not in _REFERENCE_PROPERTIES:
                continue
            for position, identifier in enumerate(values):
                if not isinstance(identifier, str):
                    continue
                if identifier in staged:
                    continue
                if identifier not in visible_references:
                    try:
                        visible_references[identifier] = await resolve_reference(
                            identifier, changeset.base_revision
                        )
                    except Exception:
                        visible_references[identifier] = None
                found = visible_references[identifier]
                if found is None:
                    diagnostics.append(
                        _diagnostic(
                            "C1-CS-010",
                            "error",
                            f"{path}/properties/{predicate}/{position}",
                            "Unresolved reference",
                        )
                    )

    if changeset.restores_from_revision and any(
        not isinstance(operation, ReplaceOperation) for operation in normalized
    ):
        diagnostics.append(
            _diagnostic(
                "C1-CS-030",
                "error",
                "/restores_from_revision",
                "Restore requires only replacements",
            )
        )

    assertions = [record for record in validated if C1 + "Assertion" in record.types]
    seen_pairs: set[tuple[str, str]] = set()
    for assertion in assertions:
        subject = _first_iri(assertion, RDF + "subject")
        claim_predicate = _first_iri(assertion, RDF + "predicate")
        if subject is None or claim_predicate is None or (subject, claim_predicate) in seen_pairs:
            continue
        seen_pairs.add((subject, claim_predicate))
        subject_record = staged.get(subject) or visible_references.get(subject)
        if subject_record is None or not _single_valued_for_subject(
            registry, subject_record, claim_predicate
        ):
            continue
        candidates = [
            item
            for item in assertions
            if _first_iri(item, RDF + "subject") == subject
            and _first_iri(item, RDF + "predicate") == claim_predicate
        ]
        if existing_assertions is not None:
            try:
                candidates.extend(
                    await existing_assertions(subject, claim_predicate, changeset.base_revision)
                )
            except Exception:
                # Conflict hints are advisory. A backend failure must be
                # handled by the service's required readiness/apply gates.
                pass
        if interval_for_assertion is None:
            continue
        for position, left in enumerate(candidates):
            if _text(left, C1 + "lifecycle") == "retracted":
                continue
            for right in candidates[position + 1 :]:
                if left.id == right.id or left.properties.get(
                    RDF + "object"
                ) == right.properties.get(RDF + "object"):
                    continue
                if _text(right, C1 + "lifecycle") == "retracted":
                    continue
                try:
                    left_interval = await interval_for_assertion(
                        left, staged, changeset.base_revision
                    )
                    right_interval = await interval_for_assertion(
                        right, staged, changeset.base_revision
                    )
                except Exception:
                    continue
                if _known_overlap(left_interval, right_interval):
                    diagnostics.append(
                        _diagnostic(
                            "C1-CS-020",
                            "info",
                            f"/assertions/{left.id}",
                            "Competing claims for a declared single-valued predicate",
                        )
                    )

    return ValidationResult(
        diagnostics=tuple(diagnostics),
        permission_preview=tuple(previews),
        records=tuple(validated),
        normalized_operations=tuple(normalized),
        minted_ids=minted,
    )
