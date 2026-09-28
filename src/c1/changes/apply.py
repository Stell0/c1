"""Reviewed ChangeSets over one serialized knowledge writer.

The workflow journal is durable intent. A knowledge commit receipt is the
authority for retry after an uncertain backend response; current bindings and
OpenFGA remain the authority for publication and reads.
"""

from __future__ import annotations

import builtins
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from c1.authorization.errors import SecurityError
from c1.authorization.fga import resource_object, scope_object
from c1.authorization.models import Binding, Decision, Operation
from c1.authorization.principal import Principal
from c1.changes.digest import receipt_message, request_digest
from c1.changes.history import HistoryService, InvalidHistoryCursor, StaleHistoryCursor
from c1.changes.idempotency import (
    IdempotencyConflict,
    idempotency_entry,
    lookup_idempotency,
    validate_request_key,
)
from c1.changes.identity import (
    IdentityPlanError,
    expand_identity,
    snapshot_identity_records,
)
from c1.changes.models import (
    ChangeOperation,
    ChangeSet,
    CreateOperation,
    InstallProfileOperation,
    MergeOperation,
    ReplaceOperation,
    ResolveOperation,
    SplitOperation,
    TransitionError,
    UndoMergeOperation,
)
from c1.changes.profiles import compare_candidate, detect_installed_registry, load_candidate
from c1.changes.validation import _REFERENCE_PROPERTIES, validate_changeset
from c1.interchange import validate_records
from c1.model.diagnostics import Diagnostic, ProfileError
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import ActivityRecord
from c1.model.time import TimeBoundary, TimeInterval
from c1.storage.mapping import record_to_document
from c1.storage.schema import _profile_marker, generated_classes, generated_core_schema

if TYPE_CHECKING:
    from c1.authorization.audit import Audit
    from c1.authorization.fga import FGA
    from c1.authorization.journal import Journal
    from c1.authorization.operations import WriterGate
    from c1.authorization.plane import AuthorizationPlane
    from c1.config import Settings
    from c1.model.profiles import ProfileRegistry
    from c1.storage.terminus import Terminus


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _principal(identifier: str) -> Principal:
    """Recreate only the stable issuer/subject for a fresh policy check."""
    if not identifier.startswith("user:") or "." not in identifier[5:]:
        raise SecurityError(503, "invalid_journal_principal")
    alias, subject = identifier[5:].split(".", 1)
    return Principal(alias, subject, "human")


def _actor_iri(identifier: str) -> str:
    principal = _principal(identifier)
    return f"urn:c1:principal:{principal.issuer_alias}:{principal.subject}"


def _public(changeset: ChangeSet) -> dict[str, Any]:
    return changeset.model_dump(mode="json")


def _same_documents(
    left: builtins.list[dict[str, Any]], right: builtins.list[dict[str, Any]]
) -> bool:
    return len(left) == len(right) and sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in left
    ) == sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in right)


_DOCUMENT = "urn:c1:ns:core#Document"
_DOCUMENT_PART = "urn:c1:ns:core#DocumentPart"
_PART_OF_DOCUMENT = "urn:c1:ns:core#partOfDocument"
_ORDER_KEY = "urn:c1:ns:core#orderKey"


def _part_document(record: dict[str, Any] | NodeRecord) -> str | None:
    types = record.types if isinstance(record, NodeRecord) else record.get("types", [])
    if _DOCUMENT_PART not in types:
        return None
    properties = (
        record.properties if isinstance(record, NodeRecord) else record.get("properties", {})
    )
    if not isinstance(properties, dict):
        return None
    values = properties.get(_PART_OF_DOCUMENT)
    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str):
        return values[0]
    return None


class ChangeService:
    """Single-process ChangeSet coordinator; all mutations hold WriterGate."""

    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        knowledge: Terminus,
        registry: ProfileRegistry,
        plane: AuthorizationPlane,
        fga: FGA,
        writer: WriterGate,
        audit: Audit,
    ) -> None:
        self.settings = settings
        self.journal = journal
        self.knowledge = knowledge
        self.registry = registry
        self.plane = plane
        self.fga = fga
        self.writer = writer
        self.audit = audit
        self.history_service = HistoryService(knowledge, plane, journal, registry)

    @staticmethod
    def _require(decision: Decision) -> None:
        if not decision.allowed:
            raise SecurityError(
                503 if decision.reason == "security_unavailable" else 403,
                "authorization_denied",
            )

    async def _identity_scope_safe(
        self, record: NodeRecord, scope_id: str, staged_scopes: dict[str, str]
    ) -> bool:
        if "urn:c1:ns:core#ResolutionRecord" in record.types:
            endpoints = record.properties.get("urn:c1:ns:core#candidate", [])
        elif "urn:c1:ns:identity#Redirect" in record.types:
            endpoints = [
                *record.properties.get("urn:c1:ns:identity#from", []),
                *record.properties.get("urn:c1:ns:identity#to", []),
            ]
        else:
            return True
        if not endpoints or not all(isinstance(value, str) for value in endpoints):
            return False
        for identifier in endpoints:
            assert isinstance(identifier, str)
            target_scope = staged_scopes.get(identifier)
            if target_scope is None:
                binding = await self.plane.bindings(identifier)
                if binding is None or binding.state != "active":
                    return False
                target_scope = binding.scope_id
            if target_scope != scope_id:
                return False
        return True

    @staticmethod
    def _transition(changeset: ChangeSet, action: Any, **kwargs: Any) -> ChangeSet:
        try:
            return changeset.transition(action, updated=_now(), **kwargs)
        except TransitionError:
            raise SecurityError(409, "invalid_changeset_state") from None

    async def _load(self, identifier: str) -> ChangeSet:
        payload = await self.journal.get("ChangeSet", identifier)
        if payload is None:
            raise SecurityError(404, "not_found")
        return ChangeSet.model_validate(payload)

    async def _save(self, changeset: ChangeSet, *entries: tuple[str, str, dict[str, Any]]) -> None:
        await self.journal.save_many([("ChangeSet", changeset.id, _public(changeset)), *entries])

    async def _permission(
        self,
        p: Principal,
        operation: ChangeOperation,
        *,
        review: bool,
        excluding: str = "",
        staged_documents: dict[str, str] | None = None,
    ) -> Decision:
        staged_documents = staged_documents or {}
        if isinstance(operation, CreateOperation):
            if operation.scope_id is None:
                return Decision(False, "permission_denied")
            decision = await self.plane.check_scope(
                p, "review" if review else "create", operation.scope_id
            )
        if isinstance(operation, ReplaceOperation):
            decision = await self.plane.check_operation(
                p,
                "review" if review else "contribute",
                operation.resource_id,
                excluding=excluding,
            )
        if not isinstance(operation, (CreateOperation, ReplaceOperation)):
            return await self.plane.check_instance(p, "schema_admin")
        if not decision.allowed:
            return decision
        old = (
            await self.knowledge.get_record(operation.resource_id, self.registry)
            if isinstance(operation, ReplaceOperation)
            else None
        )
        if _DOCUMENT_PART not in operation.record.get("types", []):
            # Retyping a part would bypass its document's structural controls.
            # Class migration/removal is not an ordinary M06 replacement.
            if old is not None and _DOCUMENT_PART in old.types:
                return Decision(False, "permission_denied")
            return decision
        target = _part_document(operation.record)
        if target is None:
            return Decision(False, "permission_denied")
        if target in staged_documents:
            readable = await self.plane.check_scope(p, "read", staged_documents[target])
        else:
            readable = await self.plane.check_read(p, target)
        if not readable.allowed:
            return readable
        document_permission = "review" if review else "contribute"
        if isinstance(operation, CreateOperation):
            if target in staged_documents:
                return await self.plane.check_scope(
                    p, document_permission, staged_documents[target]
                )
            return await self.plane.check_operation(p, document_permission, target)
        assert isinstance(operation, ReplaceOperation)
        old_document = _part_document(old) if old is not None else None
        if old_document is None:
            return Decision(False, "permission_denied")
        try:
            replacement = NodeRecord.model_validate(operation.record)
        except Exception:
            return Decision(False, "permission_denied")
        if (
            old_document == target
            and old is not None
            and old.properties.get(_ORDER_KEY) == replacement.properties.get(_ORDER_KEY)
        ):
            return decision
        for document in dict.fromkeys((old_document, target)):
            if document in staged_documents:
                allowed = await self.plane.check_scope(
                    p, document_permission, staged_documents[document]
                )
            else:
                allowed = await self.plane.check_operation(p, document_permission, document)
            if not allowed.allowed:
                return allowed
        return decision

    async def _normalize_operations(
        self, p: Principal, operations: builtins.list[ChangeOperation]
    ) -> builtins.list[ChangeOperation]:
        staged_documents = {
            str(operation.record["id"]): operation.scope_id
            for operation in operations
            if isinstance(operation, CreateOperation)
            and _DOCUMENT in operation.record.get("types", [])
            and isinstance(operation.record.get("id"), str)
            and operation.scope_id is not None
        }
        normalized: builtins.list[ChangeOperation] = []
        for operation in operations:
            if not isinstance(operation, CreateOperation) or operation.scope_id is not None:
                normalized.append(operation)
                continue
            document = _part_document(operation.record)
            if document is None:
                raise SecurityError(422, "invalid_part_document")
            if document in staged_documents:
                scope_id = staged_documents[document]
                self._require(await self.plane.check_scope(p, "read", scope_id))
            else:
                self._require(await self.plane.check_read(p, document))
                binding = await self.plane.bindings(document)
                if binding is None or binding.state != "active":
                    raise SecurityError(404, "not_found")
                scope_id = binding.scope_id
            normalized.append(
                operation.model_copy(update={"scope_id": scope_id, "inherited_from": document})
            )
        return normalized

    async def _require_all(
        self, p: Principal, changeset: ChangeSet, *, review: bool, excluding: str = ""
    ) -> None:
        staged_documents = {
            str(operation.record["id"]): operation.scope_id
            for operation in changeset.operations
            if isinstance(operation, CreateOperation)
            and _DOCUMENT in operation.record.get("types", [])
            and isinstance(operation.record.get("id"), str)
            and operation.scope_id is not None
        }
        for operation in changeset.operations:
            self._require(
                await self._permission(
                    p,
                    operation,
                    review=review,
                    excluding=excluding,
                    staged_documents=staged_documents,
                )
            )

    async def _visible(self, p: Principal, changeset: ChangeSet) -> bool:
        if p.id == changeset.author:
            return True
        staged_documents = {
            str(operation.record["id"]): operation.scope_id
            for operation in changeset.operations
            if isinstance(operation, CreateOperation)
            and _DOCUMENT in operation.record.get("types", [])
            and isinstance(operation.record.get("id"), str)
            and operation.scope_id is not None
        }
        staged_ids = {
            operation.record.get("id")
            for operation in changeset.operations
            if isinstance(operation, CreateOperation)
        }
        for operation in changeset.operations:
            decision = await self._permission(
                p, operation, review=True, staged_documents=staged_documents
            )
            if not decision.allowed:
                return False
            if isinstance(operation, ReplaceOperation):
                if not (await self.plane.check_read(p, operation.resource_id)).allowed:
                    return False
            elif isinstance(operation, CreateOperation):
                if operation.scope_id is None:
                    return False
                if not (await self.plane.check_scope(p, "read", operation.scope_id)).allowed:
                    return False
            if isinstance(operation, (CreateOperation, ReplaceOperation)):
                raw_properties = operation.record.get("properties", {})
                if not isinstance(raw_properties, dict):
                    return False
                for predicate, values in raw_properties.items():
                    if predicate not in _REFERENCE_PROPERTIES or not isinstance(values, list):
                        continue
                    for value in values:
                        if isinstance(value, str) and value not in staged_ids:
                            if not (await self.plane.check_read(p, value)).allowed:
                                return False
        return True

    async def create(self, p: Principal, body: Any, idempotency_key: str) -> dict[str, Any]:
        key = validate_request_key(idempotency_key)
        async with self.writer.hold():
            # The request key binds the caller's payload, independent of any
            # current scope used to resolve a new part's default binding.
            digest = request_digest(body.base_revision, list(body.operations), body.rationale)
            try:
                replay = await lookup_idempotency(
                    self.journal, p.id, self.settings.knowledge_database, key, digest
                )
            except IdempotencyConflict:
                raise SecurityError(422, "idempotency_conflict") from None
            if replay is not None:
                return replay
            operations = await self._normalize_operations(p, list(body.operations))
            identifier = self.settings.instance_base + "changeset-" + uuid4().hex
            changeset = ChangeSet(
                id=identifier,
                author=p.id,
                base_revision=body.base_revision,
                operations=operations,
                rationale=body.rationale,
                restores_from_revision=body.restores_from_revision,
                created=_now(),
                updated=_now(),
            )
            response = _public(changeset)
            await self._save(
                changeset,
                idempotency_entry(
                    p.id,
                    self.settings.knowledge_database,
                    key,
                    digest,
                    changeset.id,
                    response,
                ),
            )
            return response

    async def get(self, p: Principal, identifier: str) -> dict[str, Any]:
        changeset = await self._load(identifier)
        if not await self._visible(p, changeset):
            raise SecurityError(404, "not_found")
        return _public(changeset)

    async def list(self, p: Principal) -> dict[str, Any]:
        visible: builtins.list[dict[str, Any]] = []
        for payload in await self.journal.list("ChangeSet"):
            changeset = ChangeSet.model_validate(payload)
            if await self._visible(p, changeset):
                visible.append(_public(changeset))
        visible.sort(key=lambda item: (item["created"], item["id"]))
        return {"changesets": visible}

    async def edit(
        self, p: Principal, identifier: str, operations: builtins.list[ChangeOperation]
    ) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.author != p.id:
                raise SecurityError(404, "not_found")
            normalized = await self._normalize_operations(p, operations)
            revised = self._transition(changeset, "edit", operations=normalized)
            await self._save(revised, *await self._superseded(changeset))
            return _public(revised)

    async def _superseded(
        self, changeset: ChangeSet
    ) -> tuple[tuple[str, str, dict[str, Any]], ...]:
        entries: builtins.list[tuple[str, str, dict[str, Any]]] = []
        for kind, identifier in (
            ("ValidationReport", changeset.validation_report_id),
            ("ReviewDecision", changeset.review_decision_id),
        ):
            if identifier is None:
                continue
            payload = await self.journal.get(kind, identifier)
            if payload is None:
                raise SecurityError(503, "workflow_record_missing")
            entries.append(
                (kind, identifier, {**payload, "superseded": True, "superseded_at": _now()})
            )
        return tuple(entries)

    async def submit(self, p: Principal, identifier: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.author != p.id:
                raise SecurityError(404, "not_found")
            submitted = self._transition(changeset, "submit")
            await self._save(submitted)
            return await self._validate_locked(p, submitted)

    async def validate(self, p: Principal, identifier: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.author != p.id:
                raise SecurityError(404, "not_found")
            return await self._validate_locked(p, changeset)

    async def _validate_locked(self, p: Principal, changeset: ChangeSet) -> dict[str, Any]:
        if changeset.state != "submitted":
            raise SecurityError(409, "invalid_changeset_state")

        async def reference(identifier: str, revision: str) -> NodeRecord | None:
            if not (await self.plane.check_read(p, identifier)).allowed:
                return None
            return await self.knowledge.get_record(identifier, self.registry, commit=revision)

        staged_documents = {
            str(operation.record["id"]): operation.scope_id
            for operation in changeset.operations
            if isinstance(operation, CreateOperation)
            and _DOCUMENT in operation.record.get("types", [])
            and isinstance(operation.record.get("id"), str)
            and operation.scope_id is not None
        }

        async def permission(operation: ChangeOperation) -> Decision:
            return await self._permission(
                p, operation, review=False, staged_documents=staged_documents
            )

        identity_types = (ResolveOperation, MergeOperation, SplitOperation, UndoMergeOperation)
        if any(isinstance(item, identity_types) for item in changeset.operations):
            try:
                if any(not isinstance(item, identity_types) for item in changeset.operations):
                    raise IdentityPlanError("Identity operations need a separate ChangeSet")
                if await self.knowledge.head() != changeset.base_revision:
                    raise IdentityPlanError("Identity base revision is stale")
                all_records = await snapshot_identity_records(
                    self.knowledge, self.registry, changeset.base_revision
                )
                assertions = []
                for record in all_records:
                    if "urn:c1:ns:core#Assertion" in record.types:
                        assertions.append(record)

                async def authorize(identifier: str) -> bool:
                    contribute = await self.plane.check_operation(p, "contribute", identifier)
                    readable = await self.plane.check_read(p, identifier)
                    return contribute.allowed and readable.allowed

                async def list_assertions(subject: str) -> builtins.list[NodeRecord]:
                    predicate = "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject"
                    return [
                        item for item in assertions if item.properties.get(predicate) == [subject]
                    ]

                async def check_identity_scope(item: Any) -> None:
                    if isinstance(item, ResolveOperation):
                        identifiers = item.candidates
                    elif isinstance(item, MergeOperation):
                        identifiers = [item.surviving_id, item.merged_id]
                    elif isinstance(item, SplitOperation):
                        identifiers = [item.source_id]
                    else:
                        resolution = await reference(item.resolution_id, changeset.base_revision)
                        if resolution is None:
                            raise IdentityPlanError("Resolution is unavailable")
                        identifiers = [
                            value
                            for value in resolution.properties.get("urn:c1:ns:core#candidate", [])
                            if isinstance(value, str)
                        ]
                        if len(identifiers) != 2:
                            raise IdentityPlanError("Resolution is unavailable")
                    for identifier in identifiers:
                        binding = await self.plane.bindings(identifier)
                        if (
                            binding is None
                            or binding.state != "active"
                            or binding.scope_id != item.scope_id
                        ):
                            raise IdentityPlanError("Identity scope is unavailable")

                expanded: builtins.list[ChangeOperation] = []
                for item in changeset.operations:
                    assert isinstance(item, identity_types)
                    await check_identity_scope(item)
                    created = await expand_identity(
                        item,
                        base=self.settings.instance_base,
                        actor=_actor_iri(p.id),
                        resolve=lambda identifier: reference(identifier, changeset.base_revision),
                        authorize=authorize,
                        list_assertions=list_assertions,
                        all_records=all_records,
                    )
                    expanded.extend(created)
                if len(expanded) > 200 or not expanded:
                    raise IdentityPlanError("Identity plan exceeds ChangeSet limits")
                changeset = changeset.model_copy(
                    update={
                        "operations": expanded,
                        "request_digest": request_digest(
                            changeset.base_revision, expanded, changeset.rationale
                        ),
                    }
                )
            except IdentityPlanError as exc:
                report_id = self.settings.instance_base + "validation/" + uuid4().hex
                diagnostic = Diagnostic(
                    code=exc.code, severity="error", path="/operations", message=str(exc)
                )
                rejected = self._transition(changeset, "reject", reason="validation")
                rejected = rejected.model_copy(update={"validation_report_id": report_id})
                await self._save(
                    rejected,
                    (
                        "ValidationReport",
                        report_id,
                        {
                            "id": report_id,
                            "changeset_id": changeset.id,
                            "attempt": changeset.attempt,
                            "request_digest": changeset.request_digest,
                            "diagnostics": [diagnostic.model_dump(mode="json")],
                            "permission_preview": [],
                            "minted_ids": {},
                            "status": "rejected",
                        },
                    ),
                )
                return _public(rejected)

        async def restore(identifier: str, revision: str) -> NodeRecord | None:
            if not (await self.plane.check_read(p, identifier)).allowed:
                return None
            return await self.knowledge.get_record(identifier, self.registry, commit=revision)

        async def interval_for_assertion(
            assertion: NodeRecord, staged: dict[str, NodeRecord], revision: str
        ) -> TimeInterval | None:
            def iri(record: NodeRecord, predicate: str) -> str | None:
                values = record.properties.get(predicate, [])
                return values[0] if len(values) == 1 and isinstance(values[0], str) else None

            async def selected(identifier: str | None) -> NodeRecord | None:
                if identifier is None:
                    return None
                return staged.get(identifier) or await reference(identifier, revision)

            interval = await selected(iri(assertion, "urn:c1:ns:core#validDuring"))
            if interval is None:
                return None
            prefix = "http://www.w3.org/2006/time#"
            boundaries = [
                await selected(iri(interval, prefix + name)) for name in ("hasBeginning", "hasEnd")
            ]
            if any(item is None for item in boundaries):
                return None

            def boundary(record: NodeRecord) -> TimeBoundary | None:
                values = record.properties.get("urn:c1:ns:core#boundaryState", [])
                if len(values) != 1 or not isinstance(values[0], LiteralValue):
                    return None
                state = values[0].lexical
                times = [
                    value
                    for name in (
                        "inXSDDateTimeStamp",
                        "inXSDDateTime",
                        "inXSDDate",
                        "inXSDgYearMonth",
                        "inXSDgYear",
                    )
                    for value in record.properties.get(prefix + name, [])
                    if isinstance(value, LiteralValue)
                ]
                if state == "known" and len(times) == 1:
                    return TimeBoundary(
                        state="known", lexical=times[0].lexical, datatype=times[0].datatype
                    )
                if state == "unknown" and not times:
                    return TimeBoundary(state="unknown")
                if state == "unbounded" and not times:
                    return TimeBoundary(state="unbounded")
                return None

            start = boundary(boundaries[0])  # type: ignore[arg-type]
            end = boundary(boundaries[1])  # type: ignore[arg-type]
            return TimeInterval(start=start, end=end) if start and end else None

        async def profile_diagnostics(alias: str) -> builtins.list[Diagnostic]:
            try:
                _candidate, name = load_candidate(alias)
                diagnostics = compare_candidate(self.registry, alias)
            except (ValueError, OSError):
                return [
                    Diagnostic(
                        code="C1-PR-004",
                        severity="error",
                        path="/profile",
                        message="Profile is not in the trusted installed catalog",
                    )
                ]
            if name in self.registry.profiles and not diagnostics:
                diagnostics.append(
                    Diagnostic(
                        code="C1-PR-004",
                        severity="error",
                        path="/profile",
                        message="Profile is already installed",
                    )
                )
            return diagnostics

        result = await validate_changeset(
            changeset,
            registry=self.registry,
            resolve_reference=reference,
            permission_preview=permission,
            restore_record=restore,
            interval_for_assertion=interval_for_assertion,
            validate_profile=profile_diagnostics,
            mint_identifier=lambda _index, record: (
                self.settings.instance_base
                + self.registry.primary_class(record.types).kind
                + "/"
                + str(uuid4())
            ),
        )
        extra_diagnostics: builtins.list[Diagnostic] = []
        staged_scopes = {
            str(operation.record.get("id")): operation.scope_id
            for operation in result.normalized_operations
            if isinstance(operation, CreateOperation) and operation.scope_id is not None
        }
        for index, operation in enumerate(result.normalized_operations):
            if isinstance(operation, CreateOperation):
                identifier = operation.record.get("id")
                if not isinstance(identifier, str) or not identifier.startswith(
                    self.settings.instance_base
                ):
                    extra_diagnostics.append(
                        Diagnostic(
                            code="C1-CS-012",
                            severity="error",
                            path=f"/operations/{index}/record/id",
                            message="Created resource ID must use the configured instance base",
                        )
                    )
                try:
                    identity_record = NodeRecord.model_validate(operation.record)
                except Exception:
                    continue
                if operation.scope_id is None:
                    continue
                if not await self._identity_scope_safe(
                    identity_record, operation.scope_id, staged_scopes
                ):
                    extra_diagnostics.append(
                        Diagnostic(
                            code="C1-CS-040",
                            severity="error",
                            path=f"/operations/{index}",
                            message="Identity scope is unavailable",
                        )
                    )
        normalized = list(result.normalized_operations)
        if normalized != changeset.operations:
            changeset = changeset.model_copy(
                update={
                    "operations": normalized,
                    "request_digest": request_digest(
                        changeset.base_revision, normalized, changeset.rationale
                    ),
                }
            )
        report_id = self.settings.instance_base + "validation/" + uuid4().hex
        report: dict[str, Any] = {
            "id": report_id,
            "changeset_id": changeset.id,
            "attempt": changeset.attempt,
            "request_digest": changeset.request_digest,
            "diagnostics": [
                item.model_dump(mode="json") for item in (*result.diagnostics, *extra_diagnostics)
            ],
            "permission_preview": [vars(item) for item in result.permission_preview],
            "minted_ids": result.minted_ids,
            "expanded_operations": [operation.model_dump(mode="json") for operation in normalized],
            "status": "accepted" if result.accepted and not extra_diagnostics else "rejected",
        }
        if result.accepted and not extra_diagnostics:
            changeset = self._transition(changeset, "validate", validation_report_id=report_id)
        else:
            changeset = self._transition(changeset, "reject", reason="validation")
            changeset = changeset.model_copy(update={"validation_report_id": report_id})
        entries: builtins.list[tuple[str, str, dict[str, Any]]] = [
            ("ValidationReport", report_id, report)
        ]
        migrations = [
            item for item in (*result.diagnostics, *extra_diagnostics) if item.code == "C1-PR-004"
        ]
        if migrations and any(
            isinstance(operation, InstallProfileOperation) for operation in changeset.operations
        ):
            profile_operation = changeset.operations[0]
            assert isinstance(profile_operation, InstallProfileOperation)
            proposal_id = self.settings.instance_base + "migration-" + uuid4().hex
            entries.append(
                (
                    "MigrationProposal",
                    proposal_id,
                    {
                        "id": proposal_id,
                        "changeset_id": changeset.id,
                        "profile": profile_operation.profile,
                        "diagnostics": [item.model_dump(mode="json") for item in migrations],
                        "created": _now(),
                    },
                )
            )
        await self._save(changeset, *entries)
        if any(not item.allowed for item in result.permission_preview):
            raise SecurityError(403, "authorization_denied")
        return _public(changeset)

    async def get_validation(self, p: Principal, identifier: str) -> dict[str, Any]:
        changeset = await self._load(identifier)
        if not await self._visible(p, changeset) or not changeset.validation_report_id:
            raise SecurityError(404, "not_found")
        report = await self.journal.get("ValidationReport", changeset.validation_report_id)
        if report is None:
            raise SecurityError(503, "validation_report_missing")
        return report

    async def approve(self, p: Principal, identifier: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if not await self._visible(p, changeset):
                raise SecurityError(404, "not_found")
            if changeset.state != "validated":
                raise SecurityError(409, "invalid_changeset_state")
            if self.settings.independent_review and p.id == changeset.author:
                raise SecurityError(403, "independent_review_required")
            await self._require_all(p, changeset, review=True)
            decision_id = self.settings.instance_base + "review/" + uuid4().hex
            decision = {
                "id": decision_id,
                "changeset_id": changeset.id,
                "actor": p.id,
                "decision": "approved",
                "request_digest": changeset.request_digest,
                "created": _now(),
            }
            approved = self._transition(changeset, "approve", review_decision_id=decision_id)
            await self._save(approved, ("ReviewDecision", decision_id, decision))
            return _public(approved)

    async def reject(self, p: Principal, identifier: str, reason: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if not await self._visible(p, changeset):
                raise SecurityError(404, "not_found")
            await self._require_all(p, changeset, review=True)
            rejected = self._transition(changeset, "reject", reason=reason)
            decision_id = self.settings.instance_base + "review/" + uuid4().hex
            await self._save(
                rejected,
                (
                    "ReviewDecision",
                    decision_id,
                    {
                        "id": decision_id,
                        "changeset_id": changeset.id,
                        "actor": p.id,
                        "decision": "rejected",
                        "reason": reason,
                        "created": _now(),
                    },
                ),
            )
            return _public(rejected)

    async def withdraw(self, p: Principal, identifier: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.author != p.id:
                raise SecurityError(404, "not_found")
            withdrawn = self._transition(changeset, "withdraw")
            await self._save(withdrawn)
            return _public(withdrawn)

    async def rebase(self, p: Principal, identifier: str, base_revision: str) -> dict[str, Any]:
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.author != p.id:
                raise SecurityError(404, "not_found")
            rebased = self._transition(changeset, "rebase", base_revision=base_revision)
            await self._save(rebased, *await self._superseded(changeset))
            return _public(rebased)

    async def history(
        self, p: Principal, resource_id: str, limit: int, cursor: str | None
    ) -> dict[str, Any]:
        async def schema_unpublished() -> bool:
            operations = await self.journal.list("Operation")
            if any(
                item.get("kind") == "changeset_apply"
                and item.get("state") == "pending"
                and item.get("payload", {}).get("profile_alias")
                for item in operations
            ):
                return True
            installed = await detect_installed_registry(self.knowledge)
            return set(installed.profiles) != set(self.registry.profiles)

        if await schema_unpublished():
            raise SecurityError(404, "not_found")
        try:
            result = await self.history_service.list(p, resource_id, limit=limit, cursor=cursor)
        except InvalidHistoryCursor:
            raise SecurityError(400, "invalid_cursor") from None
        except StaleHistoryCursor:
            raise SecurityError(409, "stale_cursor") from None
        if await schema_unpublished():
            raise SecurityError(404, "not_found")
        if result is None:
            raise SecurityError(404, "not_found")
        return result

    async def _receipt(self, changeset: ChangeSet, actor: str) -> tuple[str, dict[str, Any]] | None:
        """Search every reachable log page before deciding a write is absent."""
        page_size = 20
        start = 0
        while True:
            page = await self.knowledge.log(start=start, count=page_size)
            for item in page:
                message = item.get("message")
                if not isinstance(message, str):
                    continue
                try:
                    receipt = json.loads(message)
                except ValueError:
                    continue
                if not isinstance(receipt, dict) or receipt.get("c1") != 2:
                    continue
                if (receipt.get("changeset"), receipt.get("attempt")) != (
                    changeset.id,
                    changeset.attempt,
                ):
                    continue
                if receipt.get("digest") != changeset.approved_digest:
                    raise SecurityError(503, "receipt_digest_mismatch")
                if (
                    receipt.get("principal") != actor
                    or receipt.get("repository") != self.settings.knowledge_database
                ):
                    raise SecurityError(503, "receipt_scope_mismatch")
                identifier = item.get("identifier")
                if not isinstance(identifier, str):
                    raise SecurityError(503, "receipt_revision_missing")
                return "branch:" + identifier, receipt
            if len(page) < page_size:
                return None
            start += len(page)

    def _crash(self, point: str) -> None:
        if self.settings.enable_probe_routes and self.settings.crash_after == point:
            os._exit(86)

    async def _planned_records(
        self, changeset: ChangeSet, actor: Principal
    ) -> tuple[builtins.list[NodeRecord], dict[str, str], dict[str, str]]:
        """Revalidate the approved records and map each new target to one scope."""
        raw: builtins.list[NodeRecord] = []
        bindings: dict[str, str] = {}
        scope_by_record: dict[str, str] = {}
        staged_parents = {
            str(operation.record["id"]): operation
            for operation in changeset.operations
            if isinstance(operation, CreateOperation)
            and _DOCUMENT in operation.record.get("types", [])
            and isinstance(operation.record.get("id"), str)
        }
        for operation in changeset.operations:
            if isinstance(operation, InstallProfileOperation):
                raise SecurityError(503, "profile_apply_not_ready")
            if not isinstance(operation, (CreateOperation, ReplaceOperation)):
                raise SecurityError(503, "identity_operation_not_expanded")
            try:
                record = NodeRecord.model_validate(operation.record)
            except Exception:
                raise SecurityError(422, "invalid_record") from None
            if isinstance(operation, CreateOperation):
                if not record.id.startswith(self.settings.instance_base):
                    raise SecurityError(422, "invalid_resource_id")
                if operation.scope_id is None:
                    raise SecurityError(422, "missing_scope")
                if (
                    _DOCUMENT_PART in record.types
                    and operation.inherited_from is not None
                    and operation.inherited_from != _part_document(record)
                ):
                    raise SecurityError(422, "inheritance_document_mismatch")
                if operation.inherited_from:
                    staged_parent = staged_parents.get(operation.inherited_from)
                    if staged_parent is not None:
                        if staged_parent.scope_id != operation.scope_id:
                            raise SecurityError(422, "inheritance_scope_conflict")
                        self._require(
                            await self.plane.check_scope(actor, "read", operation.scope_id)
                        )
                    else:
                        parent = await self.plane.bindings(operation.inherited_from)
                        self._require(await self.plane.check_read(actor, operation.inherited_from))
                        if (
                            parent is None
                            or parent.state != "active"
                            or parent.scope_id != operation.scope_id
                        ):
                            raise SecurityError(422, "inheritance_scope_conflict")
                if await self.journal.get("Binding", record.id) is not None:
                    raise SecurityError(404, "not_found")
                if await self.knowledge.get_record(record.id, self.registry) is not None:
                    raise SecurityError(404, "not_found")
                bindings[record.id] = operation.scope_id
                scope_by_record[record.id] = operation.scope_id
            else:
                if record.id != operation.resource_id:
                    raise SecurityError(422, "resource_id_mismatch")
                binding = await self.plane.bindings(record.id)
                if binding is None or binding.state != "active":
                    raise SecurityError(404, "not_found")
                if (
                    changeset.restores_from_revision
                    and not await self.history_service.restore_matches(
                        actor, record.id, changeset.restores_from_revision, record
                    )
                ):
                    raise SecurityError(422, "restore_content_mismatch")
                scope_by_record[record.id] = binding.scope_id
            raw.append(record)
        checked = validate_records(raw, self.registry)
        if len(checked.records) != len(raw):
            raise SecurityError(422, "record_canonicalization_changed_targets")
        staged = {record.id for record in checked.records}
        for record in checked.records:
            if not await self._identity_scope_safe(
                record, scope_by_record[record.id], scope_by_record
            ):
                raise SecurityError(422, "identity_scope_conflict")
        for record in checked.records:
            for predicate, values in record.properties.items():
                if predicate not in _REFERENCE_PROPERTIES:
                    continue
                for value in values:
                    if not isinstance(value, str) or value in staged:
                        continue
                    self._require(await self.plane.check_read(actor, value))
                    if (
                        await self.knowledge.get_record(
                            value, self.registry, commit=changeset.base_revision
                        )
                        is None
                    ):
                        raise SecurityError(422, "unresolved_reference")
        return checked.records, bindings, scope_by_record

    def _activities(
        self,
        changeset: ChangeSet,
        records: builtins.list[NodeRecord],
        bindings: dict[str, str],
        scope_by_record: dict[str, str],
        actor: Principal,
    ) -> tuple[builtins.list[NodeRecord], dict[str, str]]:
        """One attributed activity per touched scope, with local provenance links."""
        by_id = {record.id: record for record in records}
        result: builtins.list[NodeRecord] = []
        for scope in sorted(set(scope_by_record.values())):
            outputs = [
                operation.record["id"]
                for operation in changeset.operations
                if not isinstance(operation, InstallProfileOperation)
                and (
                    (isinstance(operation, CreateOperation) and operation.scope_id == scope)
                    or (
                        isinstance(operation, ReplaceOperation)
                        and scope_by_record.get(operation.resource_id) == scope
                    )
                )
            ]
            used = [
                identifier
                for identifier in outputs
                if identifier in by_id
                and any(
                    kind in by_id[identifier].types
                    for kind in ("urn:c1:ns:core#Source", "urn:c1:ns:core#Evidence")
                )
            ]
            activity_id = self.settings.instance_base + "activity/" + str(uuid4())
            activity = ActivityRecord(
                id=activity_id,
                actor=_actor_iri(actor.id),
                used=used,
                outputs=outputs,
                method="changeset-apply",
            ).to_node()
            result.append(activity)
            bindings[activity_id] = scope
        return result, bindings

    async def apply(self, p: Principal, identifier: str, idempotency_key: str) -> dict[str, Any]:
        key = validate_request_key(idempotency_key)
        async with self.writer.hold():
            changeset = await self._load(identifier)
            if changeset.state == "applying" and changeset.approved_digest is not None:
                try:
                    retry = await lookup_idempotency(
                        self.journal,
                        p.id,
                        self.settings.knowledge_database,
                        key,
                        changeset.approved_digest,
                    )
                except IdempotencyConflict:
                    raise SecurityError(422, "idempotency_conflict") from None
                if retry is None:
                    raise SecurityError(404, "not_found")
                await self._recover_one(changeset)
                return {**_public(await self._load(identifier)), "replayed": True}
            if not await self._visible(p, changeset):
                if changeset.state == "approved" and changeset.review_decision_id:
                    prior_decision = await self.journal.get(
                        "ReviewDecision", changeset.review_decision_id
                    )
                    if prior_decision is not None and prior_decision.get("actor") == p.id:
                        raise SecurityError(403, "authorization_denied")
                raise SecurityError(404, "not_found")
            digest = changeset.approved_digest
            if changeset.state == "applied" and digest:
                try:
                    replay = await lookup_idempotency(
                        self.journal, p.id, self.settings.knowledge_database, key, digest
                    )
                except IdempotencyConflict:
                    raise SecurityError(422, "idempotency_conflict") from None
                if replay is None:
                    raise SecurityError(409, "already_applied")
                return {**_public(changeset), "replayed": True}
            if changeset.state != "approved" or digest is None:
                raise SecurityError(409, "not_approved")
            try:
                replay = await lookup_idempotency(
                    self.journal, p.id, self.settings.knowledge_database, key, digest
                )
            except IdempotencyConflict:
                raise SecurityError(422, "idempotency_conflict") from None
            if replay is not None:
                await self._recover_one(changeset)
                return {**_public(await self._load(identifier)), "replayed": True}
            if (
                request_digest(changeset.base_revision, changeset.operations, changeset.rationale)
                != digest
            ):
                failed = self._transition(changeset, "fail", reason="payload_mismatch")
                await self._save(failed)
                raise SecurityError(409, "payload_mismatch")
            if changeset.base_revision != await self.knowledge.head():
                stale = self._transition(changeset, "stale")
                await self._save(stale)
                raise SecurityError(409, "stale_base")
            report = await self.journal.get("ValidationReport", str(changeset.validation_report_id))
            decision = await self.journal.get("ReviewDecision", str(changeset.review_decision_id))
            if (
                report is None
                or report.get("request_digest") != digest
                or report.get("status") != "accepted"
                or decision is None
                or decision.get("request_digest") != digest
                or decision.get("decision") != "approved"
            ):
                raise SecurityError(409, "approval_invalid")
            author = _principal(changeset.author)
            approver = _principal(str(decision["actor"]))
            await self._require_all(author, changeset, review=False)
            await self._require_all(approver, changeset, review=True)
            await self._require_all(p, changeset, review=True)
            if not await self._visible(approver, changeset):
                raise SecurityError(403, "approval_authority_revoked")
            if isinstance(changeset.operations[0], InstallProfileOperation):
                return await self._begin_profile_apply(p, changeset, key)
            records, bindings, scope_by_record = await self._planned_records(changeset, author)
            activities, bindings = self._activities(
                changeset, records, bindings, scope_by_record, p
            )
            batch = validate_records([*records, *activities], self.registry)
            op = Operation(
                id=str(uuid4()),
                kind="changeset_apply",
                actor=p.id,
                target=changeset.id,
                state="pending",
                targets=[record.id for record in batch.records],
                payload={
                    "base_revision": changeset.base_revision,
                    "bindings": bindings,
                    "records": [record.model_dump(mode="json") for record in batch.records],
                    "idempotency_key": key,
                },
                created=_now(),
                updated=_now(),
            )
            pending = self._transition(changeset, "begin_apply")
            entries: builtins.list[tuple[str, str, dict[str, Any]]] = [
                ("Operation", op.id, op.model_dump(mode="json")),
                idempotency_entry(
                    p.id,
                    self.settings.knowledge_database,
                    key,
                    digest,
                    changeset.id,
                    _public(pending),
                ),
            ]
            for operation in changeset.operations:
                if isinstance(operation, CreateOperation):
                    record_id = str(operation.record["id"])
                    if operation.scope_id is None:
                        raise SecurityError(422, "missing_scope")
                    binding = Binding(
                        resource_id=record_id,
                        scope_id=operation.scope_id,
                        state="provisioning",
                        inherited_from=operation.inherited_from,
                        operation_id=op.id,
                    )
                    entries.append(("Binding", record_id, binding.model_dump(mode="json")))
            for activity in activities:
                binding = Binding(
                    resource_id=activity.id,
                    scope_id=bindings[activity.id],
                    state="provisioning",
                    operation_id=op.id,
                )
                entries.append(("Binding", activity.id, binding.model_dump(mode="json")))
            await self._save(pending, *entries)
            self._crash("journal")
            await self._reconcile(op, pending)
            return _public(await self._load(identifier))

    async def _begin_profile_apply(
        self, p: Principal, changeset: ChangeSet, key: str
    ) -> dict[str, Any]:
        operation = changeset.operations[0]
        if not isinstance(operation, InstallProfileOperation):
            raise SecurityError(503, "invalid_profile_changeset")
        diagnostics = await self._current_profile_diagnostics(operation.profile)
        if any(item.severity == "error" for item in diagnostics):
            raise SecurityError(409, "profile_installation_changed")
        op = Operation(
            id=str(uuid4()),
            kind="changeset_apply",
            actor=p.id,
            target=changeset.id,
            state="pending",
            targets=[],
            payload={
                "profile_alias": operation.profile,
                "base_revision": changeset.base_revision,
                "idempotency_key": key,
            },
            created=_now(),
            updated=_now(),
        )
        pending = self._transition(changeset, "begin_apply")
        await self._save(
            pending,
            ("Operation", op.id, op.model_dump(mode="json")),
            idempotency_entry(
                p.id,
                self.settings.knowledge_database,
                key,
                str(changeset.approved_digest),
                changeset.id,
                _public(pending),
            ),
        )
        self._crash("journal")
        await self._reconcile(op, pending)
        return _public(await self._load(changeset.id))

    async def _current_profile_diagnostics(self, alias: str) -> builtins.list[Diagnostic]:
        try:
            _candidate, name = load_candidate(alias)
            diagnostics = compare_candidate(self.registry, alias)
        except ProfileError as exc:
            return list(exc.diagnostics)
        except (ValueError, OSError):
            return [
                Diagnostic(
                    code="C1-PR-004",
                    severity="error",
                    path="/profile",
                    message="Profile is not in the trusted installed catalog",
                )
            ]
        if name in self.registry.profiles and not diagnostics:
            diagnostics.append(
                Diagnostic(
                    code="C1-PR-004",
                    severity="error",
                    path="/profile",
                    message="Profile is already installed",
                )
            )
        return diagnostics

    async def _recover_one(self, changeset: ChangeSet) -> None:
        entries = await self.journal.list("Operation")
        matching = [
            Operation.model_validate(item)
            for item in entries
            if item.get("kind") == "changeset_apply"
            and item.get("target") == changeset.id
            and item.get("state") == "pending"
        ]
        if len(matching) != 1:
            raise SecurityError(503, "recovery_operation_missing")
        await self._reconcile(matching[0], changeset)

    async def _reconcile(self, op: Operation, changeset: ChangeSet) -> None:
        if op.state != "pending" or changeset.state != "applying":
            raise SecurityError(503, "recovery_state_mismatch")
        if changeset.approved_digest is None:
            raise SecurityError(503, "recovery_digest_missing")
        decision = await self.journal.get("ReviewDecision", str(changeset.review_decision_id))
        if decision is None:
            raise SecurityError(503, "recovery_approval_missing")
        await self._require_all(
            _principal(changeset.author), changeset, review=False, excluding=op.id
        )
        await self._require_all(
            _principal(str(decision["actor"])), changeset, review=True, excluding=op.id
        )
        await self._require_all(_principal(op.actor), changeset, review=True, excluding=op.id)
        if op.payload.get("profile_alias"):
            await self._reconcile_profile(op, changeset)
            return
        found = await self._receipt(changeset, op.actor)
        if found is None:
            if await self.knowledge.head() != changeset.base_revision:
                raise SecurityError(503, "unreconciled_knowledge_head")
            records = [NodeRecord.model_validate(value) for value in op.payload["records"]]
            message = receipt_message(
                changeset_id=changeset.id,
                attempt=changeset.attempt,
                principal_id=op.actor,
                repository=self.settings.knowledge_database,
                digest=changeset.approved_digest,
            )
            revision = await self.knowledge.upsert_records(
                validate_records(records, self.registry),
                self.registry,
                expected_head=changeset.base_revision,
                message=message,
            )
            found = revision, json.loads(message)
            self._crash("commit")
        revision, _receipt = found
        op.payload["revision"] = revision
        op.updated = _now()
        await self.journal.save_many([("Operation", op.id, op.model_dump(mode="json"))])
        bindings: dict[str, str] = op.payload["bindings"]
        for identifier, scope in bindings.items():
            current = await self.fga.bindings(resource_object(identifier))
            expected = [scope_object(scope)]
            if current and current != expected:
                raise SecurityError(503, "publication_binding_conflict")
            if not current:
                await self.fga.bind(resource_object(identifier), expected[0])
        self._crash("tuple")
        for identifier, scope in bindings.items():
            if await self.fga.bindings(resource_object(identifier)) != [scope_object(scope)]:
                raise SecurityError(503, "publication_not_confirmed")
        for raw in op.payload["records"]:
            record = NodeRecord.model_validate(raw)
            actual = await self.knowledge.get_record(record.id, self.registry, commit=revision)
            if (
                actual is None
                or actual.id != record.id
                or set(actual.types) != set(record.types)
                or {key: frozenset(values) for key, values in actual.properties.items() if values}
                != {key: frozenset(values) for key, values in record.properties.items() if values}
            ):
                raise SecurityError(503, "publication_content_mismatch")
        self._crash("confirm")
        await self._finish(op, changeset, revision, bindings)

    async def _reconcile_profile(self, op: Operation, changeset: ChangeSet) -> None:
        alias = str(op.payload["profile_alias"])
        try:
            candidate, name = load_candidate(alias)
        except (ValueError, OSError):
            raise SecurityError(503, "profile_catalog_unavailable") from None
        schema = await self.knowledge.schema_documents()
        core = generated_core_schema(candidate)
        current = [*core]
        for installed_name in self.registry.profiles:
            if installed_name != "core":
                current.extend(generated_classes(self.registry, installed_name))
        target = [*current, *generated_classes(candidate, name)]
        marker = record_to_document(
            _profile_marker(candidate, name), candidate, self.knowledge.config.instance_base
        )
        existing_marker = await self.knowledge.get(str(marker["@id"]))
        if _same_documents(schema, current) and existing_marker is None:
            if await self.knowledge.head() != changeset.base_revision:
                raise SecurityError(503, "unreconciled_schema_head")
            await self.knowledge._insert(
                generated_classes(candidate, name),
                expected_head=changeset.base_revision,
                message=f"Install C1 profile {name} {candidate.profiles[name].version}",
                graph_type="schema",
            )
            self._crash("commit")
            schema = await self.knowledge.schema_documents()
        if not _same_documents(schema, target):
            raise SecurityError(503, "profile_schema_mismatch")
        if existing_marker is None:
            digest = changeset.approved_digest
            if digest is None:
                raise SecurityError(503, "recovery_digest_missing")
            message = receipt_message(
                changeset_id=changeset.id,
                attempt=changeset.attempt,
                principal_id=op.actor,
                repository=self.settings.knowledge_database,
                digest=digest,
            )
            await self.knowledge._insert(
                [marker], expected_head=await self.knowledge.head(), message=message
            )
        elif existing_marker != marker:
            raise SecurityError(503, "profile_marker_mismatch")
        found = await self._receipt(changeset, op.actor)
        if found is None:
            raise SecurityError(503, "profile_receipt_missing")
        revision, _receipt = found
        installed = await detect_installed_registry(self.knowledge)
        if name not in installed.profiles:
            raise SecurityError(503, "profile_installation_incomplete")
        # Update the shared registry object held by Runtime and security code.
        self.registry.classes = installed.classes
        self.registry.predicates = installed.predicates
        self.registry.contexts = installed.contexts
        self.registry.shapes = installed.shapes
        self.registry.profiles = installed.profiles
        self._crash("confirm")
        await self._finish(op, changeset, revision, {})

    async def _finish(
        self, op: Operation, changeset: ChangeSet, revision: str, bindings: dict[str, str]
    ) -> None:
        if changeset.approved_digest is None:
            raise SecurityError(503, "recovery_digest_missing")
        receipt_id = self.settings.instance_base + "receipt/" + uuid4().hex
        applied = self._transition(changeset, "applied", apply_receipt_id=receipt_id)
        receipt = {
            "id": receipt_id,
            "changeset_id": changeset.id,
            "attempt": changeset.attempt,
            "knowledge_commit": revision,
            "request_digest": changeset.approved_digest,
            "created": _now(),
        }
        op.state = "applied"
        op.updated = _now()
        entries: builtins.list[tuple[str, str, dict[str, Any]]] = [
            ("Operation", op.id, op.model_dump(mode="json")),
            ("ApplyReceipt", receipt_id, receipt),
            idempotency_entry(
                op.actor,
                self.settings.knowledge_database,
                str(op.payload["idempotency_key"]),
                changeset.approved_digest,
                changeset.id,
                _public(applied),
            ),
        ]
        for identifier in bindings:
            binding = await self.plane.bindings(identifier)
            if binding is None or binding.state != "provisioning" or binding.operation_id != op.id:
                raise SecurityError(503, "publication_binding_missing")
            binding.state = "active"
            entries.append(("Binding", identifier, binding.model_dump(mode="json")))
        await self._save(applied, *entries)

    async def recover(self) -> None:
        async with self.writer.hold():
            for value in sorted(
                await self.journal.list("Operation"), key=lambda item: str(item.get("created", ""))
            ):
                if value.get("kind") != "changeset_apply" or value.get("state") != "pending":
                    continue
                op = Operation.model_validate(value)
                changeset = await self._load(op.target)
                await self._reconcile(op, changeset)
