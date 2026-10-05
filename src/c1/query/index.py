"""Workflow-head-bound projection of current security bindings.

This is a candidate index, never a permission cache. Callers must perform
live OpenFGA and current-binding checks before reading knowledge records.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Operation, Scope


class IndexUnavailable(RuntimeError):
    """The journal projection cannot safely be used."""


class IndexHeadChanged(IndexUnavailable):
    """The workflow head changed while building a projection."""


@dataclass(frozen=True, slots=True)
class BindingSnapshot:
    head: str
    bindings: tuple[Binding, ...]
    active_scopes: frozenset[str]
    pending_resources: frozenset[str]
    pending_scopes: frozenset[str]
    global_publication_pending: bool
    history_manifest: bytes | None = None
    # M14a B1: every storage class each journaled resource was ever written
    # with. Complete for tracked IDs, so class probes stay exact; untracked IDs
    # are absent and keep all-class probes.
    class_hints: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def candidates(
        self,
        readable_scopes: frozenset[str],
        *,
        scope_ids: frozenset[str] | None = None,
        candidate_ids: frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        if self.global_publication_pending:
            raise IndexUnavailable("knowledge publication is pending")
        selected_scopes = readable_scopes & self.active_scopes - self.pending_scopes
        if scope_ids is not None:
            selected_scopes &= scope_ids
        return tuple(
            sorted(
                binding.resource_id
                for binding in self.bindings
                if binding.state == "active"
                and binding.scope_id in selected_scopes
                and binding.resource_id not in self.pending_resources
                and (candidate_ids is None or binding.resource_id in candidate_ids)
            )
        )


@dataclass(frozen=True, slots=True)
class _PreparedSnapshot:
    snapshot: BindingSnapshot
    cache_token: object


class CurrentBindingIndex:
    """Rebuild on a new exact head; discard on any journal error."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self._snapshot: BindingSnapshot | None = None
        self._cache_token = object()
        self._lock = asyncio.Lock()

    async def snapshot(self, expected_head: str) -> BindingSnapshot:
        return await self._read_snapshot(expected_head, check_initial_head=True)

    async def _snapshot_after_head(self, expected_head: str) -> BindingSnapshot:
        """Use a caller's freshly read head, retaining the cold enumeration guard.

        This private candidate-only path requires live authorization followed by
        another exact-head check before the caller can retrieve knowledge.
        """
        return await self._read_snapshot(expected_head, check_initial_head=False)

    async def _prepare_after_head(self, expected_head: str) -> _PreparedSnapshot:
        """Prepare private candidates for the planner's post-authorization guard.

        Cold candidates never enter the shared cache here. The sole caller must
        perform fresh authorization and verify the exact head before knowledge
        retrieval or synchronous publication through ``_publish_verified``.
        """
        async with self._lock:
            token = self._cache_token
            if self._snapshot is not None and self._snapshot.head == expected_head:
                return _PreparedSnapshot(self._snapshot, token)
            try:
                records = await self._enumerate_records()
                return _PreparedSnapshot(self._make_snapshot(expected_head, records), token)
            except Exception as exc:
                # A failed private read must not invalidate another caller's
                # verified cache, including one published during enumeration.
                raise IndexUnavailable("current binding index unavailable") from exc

    def _publish_verified(self, prepared: _PreparedSnapshot) -> None:
        """CAS publication after the planner's exact post-authorization head."""
        if prepared.cache_token is self._cache_token and self._snapshot is not prepared.snapshot:
            self._snapshot = prepared.snapshot
            self._cache_token = object()

    async def _enumerate_records(self) -> tuple[list[Scope], list[Binding], list[Operation], bytes]:
        rows = await self.journal.list_many({"Scope", "Binding", "Operation", "ChangeSet"})
        return (
            [Scope.model_validate(item) for item in rows["Scope"]],
            [Binding.model_validate(item) for item in rows["Binding"]],
            [Operation.model_validate(item) for item in rows["Operation"]],
            json.dumps(
                {"ChangeSet": rows["ChangeSet"], "Operation": rows["Operation"]},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )

    @staticmethod
    def _make_snapshot(
        expected_head: str, records: tuple[list[Scope], list[Binding], list[Operation], bytes]
    ) -> BindingSnapshot:
        scopes, bindings, operations, history_manifest = records
        if len({scope.id for scope in scopes}) != len(scopes) or len(
            {binding.resource_id for binding in bindings}
        ) != len(bindings):
            raise IndexUnavailable("duplicate current security records")
        pending = [operation for operation in operations if operation.state == "pending"]
        return BindingSnapshot(
            head=expected_head,
            bindings=tuple(bindings),
            active_scopes=frozenset(scope.id for scope in scopes if scope.state == "active"),
            pending_resources=frozenset(
                resource_id for operation in pending for resource_id in operation.targets
            ),
            pending_scopes=frozenset(
                operation.target
                for operation in pending
                if operation.kind in {"scope_create", "scope_retire", "membership"}
            ),
            global_publication_pending=any(
                operation.kind == "changeset_apply" and bool(operation.payload.get("profile_alias"))
                for operation in pending
            ),
            history_manifest=history_manifest,
            class_hints=MappingProxyType(_class_hints(operations)),
        )

    async def _read_snapshot(
        self, expected_head: str, *, check_initial_head: bool
    ) -> BindingSnapshot:
        async with self._lock:
            token = self._cache_token
            try:
                if check_initial_head and await self.journal.head() != expected_head:
                    raise IndexHeadChanged("workflow head changed")
                if self._snapshot is not None and self._snapshot.head == expected_head:
                    return self._snapshot
                records = await self._enumerate_records()
                if await self.journal.head() != expected_head:
                    raise IndexHeadChanged("workflow head changed")
                snapshot = self._make_snapshot(expected_head, records)
                self._publish_verified(_PreparedSnapshot(snapshot, token))
                return snapshot
            except IndexHeadChanged:
                if token is self._cache_token:
                    self._snapshot = None
                    self._cache_token = object()
                raise
            except Exception as exc:
                if token is self._cache_token:
                    self._snapshot = None
                    self._cache_token = object()
                raise IndexUnavailable("current binding index unavailable") from exc


def _class_hints(operations: list[Operation]) -> dict[str, frozenset[str]]:
    """Storage classes written for each resource by journaled knowledge writes.

    Instance documents are written only by applied ChangeSets and the
    provisioning operations, and each operation keeps its full records.
    """
    seen: dict[str, set[str]] = {}
    for operation in operations:
        if operation.state != "applied":
            continue
        if operation.kind == "changeset_apply":
            raw_records = operation.payload.get("records", ())
        elif operation.kind in {"provision", "probe_revision"}:
            raw_records = [operation.payload.get("record")]
        else:
            continue
        for raw in raw_records:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                continue
            types = raw.get("types")
            if isinstance(types, list) and all(isinstance(item, str) for item in types):
                seen.setdefault(raw["id"], set()).update(types)
    return {identifier: frozenset(types) for identifier, types in seen.items()}
