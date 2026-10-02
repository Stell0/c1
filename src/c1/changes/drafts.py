"""Documentation-draft ChangeSet rules (M11 D5–D8, ADR-0022).

The rules read only what the service injects: scope kinds from current
security state, records the submitter may read at the base revision, and the
readable applicability checks of one rule. They never infer applicability.

* ``C1-CS-051`` a new draft, or a new Document it names, outside a drafting scope;
* ``C1-CS-050`` an approved draft whose applicability check does not match its
  exact target, or is not the latest readable check of that rule and target;
* ``C1-CS-052`` a publication receipt created in a drafting scope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from c1.changes.models import ChangeOperation, CreateOperation, ReplaceOperation
from c1.model.diagnostics import Diagnostic
from c1.model.nodes import NodeRecord

S = "urn:c1:ns:software#"
DRAFT = S + "DocumentationDraft"
CHECK = S + "ApplicabilityCheck"
PUBLICATION = S + "ExternalPublication"

ScopeKind = Callable[[str], Awaitable[str | None]]
BindingScope = Callable[[str], Awaitable[str | None]]
Reference = Callable[[str], Awaitable[NodeRecord | None]]
ChecksFor = Callable[[str], Awaitable[list[NodeRecord]]]


def _iris(record: NodeRecord, predicate: str) -> list[str]:
    return [value for value in record.properties.get(predicate, []) if isinstance(value, str)]


def _text(record: NodeRecord, predicate: str) -> str | None:
    for value in record.properties.get(predicate, []):
        lexical = getattr(value, "lexical", None)
        if isinstance(lexical, str):
            return lexical
    return None


def _target(record: NodeRecord) -> tuple[frozenset[str], frozenset[str]]:
    return (
        frozenset(_iris(record, S + "targetSnapshotRef")),
        frozenset(_iris(record, S + "targetContractRef")),
    )


def _record(operation: ChangeOperation) -> NodeRecord | None:
    if not isinstance(operation, CreateOperation | ReplaceOperation):
        return None
    try:
        return NodeRecord.model_validate(operation.record)
    except Exception:
        return None


async def draft_diagnostics(
    operations: Sequence[ChangeOperation],
    *,
    scope_kind: ScopeKind,
    binding_scope: BindingScope,
    reference: Reference,
    checks_for: ChecksFor,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    created_scopes = {
        str(operation.record.get("id")): operation.scope_id
        for operation in operations
        if isinstance(operation, CreateOperation) and operation.scope_id is not None
    }

    async def drafting(scope: str | None) -> bool:
        return scope is not None and await scope_kind(scope) == "drafting"

    for index, operation in enumerate(operations):
        record = _record(operation)
        if record is None:
            continue
        path = f"/operations/{index}"
        if PUBLICATION in record.types and isinstance(operation, CreateOperation):
            if await drafting(operation.scope_id):
                diagnostics.append(
                    Diagnostic(
                        code="C1-CS-052",
                        severity="error",
                        path=path,
                        message="A publication receipt cannot be created in a drafting scope",
                    )
                )
            continue
        if DRAFT not in record.types:
            continue
        if isinstance(operation, CreateOperation):
            documents = _iris(record, S + "documentRef")
            scopes = [operation.scope_id] + [
                created_scopes[item] if item in created_scopes else await binding_scope(item)
                for item in documents
            ]
            if not all([await drafting(scope) for scope in scopes]):
                diagnostics.append(
                    Diagnostic(
                        code="C1-CS-051",
                        severity="error",
                        path=path,
                        message="draft_requires_drafting_scope",
                    )
                )
        if _text(record, S + "draftState") == "approved" and not await _fresh(
            record, reference, checks_for
        ):
            diagnostics.append(
                Diagnostic(
                    code="C1-CS-050",
                    severity="error",
                    path=path,
                    message="applicability_revalidation_required",
                )
            )
    return diagnostics


async def _fresh(draft: NodeRecord, reference: Reference, checks_for: ChecksFor) -> bool:
    """The draft names the latest readable rule check for exactly its target."""
    names = _iris(draft, S + "applicabilityCheckRef")
    if len(names) != 1:
        return False
    check = await reference(names[0])
    if check is None or CHECK not in check.types or _target(check) != _target(draft):
        return False
    rule = _text(check, S + "ruleRef")
    checked = _text(check, S + "checkedAt")
    if rule is None or checked is None:
        return False
    for other in await checks_for(rule):
        if other.id == check.id or _target(other) != _target(check):
            continue
        later = _text(other, S + "checkedAt")
        if later is not None and (later, other.id) > (checked, check.id):
            return False
    return True
