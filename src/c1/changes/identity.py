"""Expand explicit identity decisions into ordinary, reviewable knowledge writes.

The caller supplies an authorized record resolver and a *complete* repository
snapshot of assertions. Missing plans fail closed, including when a relevant
assertion is not readable by the author. No assertion or binding is copied.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from c1.changes.models import (
    AssertionAssignment,
    ChangeOperation,
    CreateOperation,
    MergeOperation,
    ReplaceOperation,
    ResolveOperation,
    SplitOperation,
    UndoMergeOperation,
)
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import document_to_record

if TYPE_CHECKING:
    from c1.storage.terminus import Terminus

C1 = "urn:c1:ns:core#"
IDENTITY = "urn:c1:ns:identity#"
RDF_SUBJECT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject"
SKOS_ALT = "http://www.w3.org/2004/02/skos/core#altLabel"
SKOS_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
PROV_ACTOR = "http://www.w3.org/ns/prov#wasAttributedTo"

Resolver = Callable[[str], Awaitable[NodeRecord | None]]
Authority = Callable[[str], Awaitable[bool]]
AssertionLister = Callable[[str], Awaitable[Sequence[NodeRecord]]]


class IdentityPlanError(ValueError):
    """Publicly safe error: never includes an unseen resource identifier."""

    code = "C1-CS-040"


async def snapshot_identity_records(
    knowledge: Terminus, registry: ProfileRegistry, expected_head: str
) -> list[NodeRecord]:
    """Read every document in fixed pages under the single-writer gate.

    Any incomplete or changing page sequence fails.
    """
    page_size = 200
    maximum = 100_000
    if await knowledge.head() != expected_head:
        raise IdentityPlanError("Identity base revision is stale")
    records: list[NodeRecord] = []
    seen: set[str] = set()
    for offset in range(0, maximum + page_size, page_size):
        payload = await knowledge.documents_page(skip=offset, count=page_size, commit=expected_head)
        if not isinstance(payload, list) or len(payload) > page_size:
            raise IdentityPlanError("Identity snapshot is incomplete")
        for document in payload:
            if not isinstance(document, dict):
                raise IdentityPlanError("Identity snapshot is incomplete")
            record = document_to_record(document, registry)
            if record.id in seen:
                raise IdentityPlanError("Identity snapshot is incomplete")
            seen.add(record.id)
            records.append(record)
        if len(payload) < page_size:
            if await knowledge.head() != expected_head:
                raise IdentityPlanError("Identity snapshot changed")
            return records
    raise IdentityPlanError("Identity snapshot exceeds limit")


def _literal(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD_STRING)


def _record_id(base: str, kind: str) -> str:
    return base + kind + "/" + str(uuid4())


def _replace(record: NodeRecord, *, reason: str) -> ReplaceOperation:
    return ReplaceOperation(
        resource_id=record.id, record=record.model_dump(mode="json"), reason=reason
    )


def _with_property(
    record: NodeRecord, predicate: str, values: list[str | LiteralValue]
) -> NodeRecord:
    properties = {key: list(items) for key, items in record.properties.items()}
    properties[predicate] = values
    return record.model_copy(update={"properties": properties})


def _resolution(
    base: str, candidates: list[str], decision: str, rationale: str, actor: str
) -> NodeRecord:
    return NodeRecord(
        id=_record_id(base, "resolution"),
        types=[C1 + "ResolutionRecord"],
        properties={
            C1 + "candidate": cast(list[str | LiteralValue], candidates),
            C1 + "decision": [_literal(decision)],
            C1 + "rationale": [_literal(rationale)],
            PROV_ACTOR: [actor],
        },
    )


def _assertion_id(record: NodeRecord) -> str | None:
    values = record.properties.get(RDF_SUBJECT, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


async def _entity(
    identifier: str, resolve: Resolver, authorize: Authority, registry: ProfileRegistry
) -> NodeRecord:
    if not await authorize(identifier):
        raise IdentityPlanError("Identity operation target is unavailable")
    record = await resolve(identifier)
    if record is None or not registry.is_entity(record.types):
        raise IdentityPlanError("Identity operation target is unavailable")
    return record


async def _assignment_operations(
    source: str,
    destination: str,
    plan: list[AssertionAssignment],
    *,
    list_assertions: AssertionLister,
    authorize: Authority,
    resolve: Resolver,
    reason: str,
) -> list[ReplaceOperation]:
    # The repository enumeration must be complete, not merely author-visible.
    assertions = list(await list_assertions(source))
    found = {record.id: record for record in assertions if _assertion_id(record) == source}
    planned = {item.assertion_id: item for item in plan}
    if len(planned) != len(plan) or set(planned) != set(found):
        raise IdentityPlanError("Incomplete assertion reassignment")
    result: list[ReplaceOperation] = []
    for identifier in sorted(found):
        item = planned[identifier]
        if not await authorize(identifier) or await resolve(identifier) is None:
            raise IdentityPlanError("Incomplete assertion reassignment")
        record = found[identifier]
        if item.action == "keep":
            continue
        if item.action == "move":
            updated = _with_property(record, RDF_SUBJECT, [destination])
        else:
            updated = _with_property(record, C1 + "lifecycle", [_literal("retracted")])
        result.append(_replace(updated, reason=reason))
    return result


async def expand_identity(
    operation: ResolveOperation | MergeOperation | SplitOperation | UndoMergeOperation,
    *,
    base: str,
    actor: str,
    resolve: Resolver,
    authorize: Authority,
    list_assertions: AssertionLister,
    all_records: Sequence[NodeRecord] = (),
    registry: ProfileRegistry | None = None,
) -> list[ChangeOperation]:
    """Expand against one base revision; all reads/authority checks fail closed."""
    registry = registry or ProfileRegistry()
    if isinstance(operation, ResolveOperation):
        if len(set(operation.candidates)) != len(operation.candidates):
            raise IdentityPlanError("Invalid identity candidates")
        candidate_records: list[NodeRecord] = []
        for identifier in operation.candidates:
            candidate_records.append(await _entity(identifier, resolve, authorize, registry))
        resolution = _resolution(
            base, operation.candidates, operation.decision, operation.rationale, actor
        )
        return [
            *[
                _replace(record, reason="identity resolution: " + operation.rationale)
                for record in candidate_records
            ],
            CreateOperation(record=resolution.model_dump(mode="json"), scope_id=operation.scope_id),
        ]

    if isinstance(operation, MergeOperation):
        if operation.surviving_id == operation.merged_id:
            raise IdentityPlanError("Invalid identity candidates")
        survivor = await _entity(operation.surviving_id, resolve, authorize, registry)
        merged = await _entity(operation.merged_id, resolve, authorize, registry)
        assignment = await _assignment_operations(
            merged.id,
            survivor.id,
            operation.assertion_plan,
            list_assertions=list_assertions,
            authorize=authorize,
            resolve=resolve,
            reason="identity merge: " + operation.rationale,
        )
        copied_aliases: list[LiteralValue] = []
        if operation.alias_plan == "copy":
            aliases = list(survivor.properties.get(SKOS_ALT, []))
            for value in (
                *merged.properties.get(SKOS_LABEL, []),
                *merged.properties.get(SKOS_ALT, []),
            ):
                if not isinstance(value, LiteralValue):
                    raise IdentityPlanError("Invalid merge alias")
                if value not in aliases and value not in survivor.properties.get(SKOS_LABEL, []):
                    aliases.append(value)
                    copied_aliases.append(value)
            survivor = _with_property(survivor, SKOS_ALT, aliases)
        merged = _with_property(merged, C1 + "lifecycle", [_literal("superseded")])
        resolution = _resolution(
            base, [survivor.id, merged.id], "merge", operation.rationale, actor
        )
        redirect = NodeRecord(
            id=_record_id(base, "redirect"),
            types=[IDENTITY + "Redirect"],
            properties={
                IDENTITY + "from": [merged.id],
                IDENTITY + "to": [survivor.id],
                IDENTITY + "resolution": [resolution.id],
                C1 + "lifecycle": [_literal("active")],
                IDENTITY + "copiedAlias": cast(list[str | LiteralValue], copied_aliases),
            },
        )
        return [
            _replace(survivor, reason="identity merge: " + operation.rationale),
            _replace(merged, reason="identity merge: " + operation.rationale),
            *assignment,
            CreateOperation(record=resolution.model_dump(mode="json"), scope_id=operation.scope_id),
            CreateOperation(record=redirect.model_dump(mode="json"), scope_id=operation.scope_id),
        ]

    if isinstance(operation, SplitOperation):
        source = await _entity(operation.source_id, resolve, authorize, registry)
        try:
            new_raw = dict(operation.new_entity)
            new_raw.setdefault("id", _record_id(base, "entity"))
            new_entity = NodeRecord.model_validate(new_raw)
        except Exception as exc:
            raise IdentityPlanError("Invalid split entity") from exc
        if not registry.is_entity(new_entity.types) or not new_entity.id.startswith(base):
            raise IdentityPlanError("Invalid split entity")
        assignment = await _assignment_operations(
            source.id,
            new_entity.id,
            operation.assertion_plan,
            list_assertions=list_assertions,
            authorize=authorize,
            resolve=resolve,
            reason="identity split: " + operation.rationale,
        )
        resolution = _resolution(
            base, [source.id, new_entity.id], "split", operation.rationale, actor
        )
        return [
            CreateOperation(record=new_entity.model_dump(mode="json"), scope_id=operation.scope_id),
            _replace(source, reason="identity split: " + operation.rationale),
            *assignment,
            CreateOperation(record=resolution.model_dump(mode="json"), scope_id=operation.scope_id),
        ]

    previous = await resolve(operation.resolution_id)
    if previous is None or C1 + "ResolutionRecord" not in previous.types:
        raise IdentityPlanError("Resolution is unavailable")
    if not await authorize(operation.resolution_id):
        raise IdentityPlanError("Resolution is unavailable")
    candidates = previous.properties.get(C1 + "candidate", [])
    decision = previous.properties.get(C1 + "decision", [])
    if (
        len(candidates) != 2
        or not all(isinstance(item, str) for item in candidates)
        or len(decision) != 1
        or not isinstance(decision[0], LiteralValue)
        or decision[0].lexical != "merge"
    ):
        raise IdentityPlanError("Resolution cannot be undone")
    survivor_id, merged_id = cast(list[str], candidates)
    survivor = await _entity(survivor_id, resolve, authorize, registry)
    merged = await _entity(merged_id, resolve, authorize, registry)
    assignment = await _assignment_operations(
        survivor.id,
        merged.id,
        operation.reassignment_plan,
        list_assertions=list_assertions,
        authorize=authorize,
        resolve=resolve,
        reason="undo identity merge: " + operation.rationale,
    )
    merged = _with_property(merged, C1 + "lifecycle", [_literal("active")])
    resolution = _resolution(
        base, [survivor.id, merged.id], "undo_merge", operation.rationale, actor
    )
    redirects = [
        record
        for record in all_records
        if IDENTITY + "Redirect" in record.types
        and record.properties.get(IDENTITY + "resolution") == [operation.resolution_id]
        and record.properties.get(C1 + "lifecycle") == [_literal("active")]
    ]
    if len(redirects) != 1 or not await authorize(redirects[0].id):
        raise IdentityPlanError("Active redirect is unavailable")
    redirect = _with_property(redirects[0], C1 + "lifecycle", [_literal("retracted")])
    copied = redirect.properties.get(IDENTITY + "copiedAlias", [])
    if any(not isinstance(value, LiteralValue) for value in copied):
        raise IdentityPlanError("Redirect alias record is invalid")
    survivor = _with_property(
        survivor,
        SKOS_ALT,
        [value for value in survivor.properties.get(SKOS_ALT, []) if value not in copied],
    )
    return [
        _replace(previous, reason="undo identity merge: " + operation.rationale),
        _replace(survivor, reason="undo identity merge: " + operation.rationale),
        _replace(merged, reason="undo identity merge: " + operation.rationale),
        _replace(redirect, reason="undo identity merge: " + operation.rationale),
        *assignment,
        CreateOperation(record=resolution.model_dump(mode="json"), scope_id=operation.scope_id),
    ]
