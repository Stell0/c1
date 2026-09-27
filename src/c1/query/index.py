"""Workflow-head-bound projection of current security bindings.

This is a candidate index, never a permission cache. Callers must perform
live OpenFGA and current-binding checks before reading knowledge records.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

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


class CurrentBindingIndex:
    """Rebuild on a new exact head; discard on any journal error."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self._snapshot: BindingSnapshot | None = None
        self._lock = asyncio.Lock()

    async def snapshot(self, expected_head: str) -> BindingSnapshot:
        async with self._lock:
            try:
                if await self.journal.head() != expected_head:
                    raise IndexHeadChanged("workflow head changed")
                if self._snapshot is not None and self._snapshot.head == expected_head:
                    return self._snapshot
                rows = await self.journal.list_many({"Scope", "Binding", "Operation"})
                scopes = [Scope.model_validate(item) for item in rows["Scope"]]
                bindings = [Binding.model_validate(item) for item in rows["Binding"]]
                operations = [Operation.model_validate(item) for item in rows["Operation"]]
                if await self.journal.head() != expected_head:
                    raise IndexHeadChanged("workflow head changed")
                if len({scope.id for scope in scopes}) != len(scopes) or len(
                    {binding.resource_id for binding in bindings}
                ) != len(bindings):
                    raise IndexUnavailable("duplicate current security records")
                pending = [operation for operation in operations if operation.state == "pending"]
                snapshot = BindingSnapshot(
                    head=expected_head,
                    bindings=tuple(bindings),
                    active_scopes=frozenset(
                        scope.id for scope in scopes if scope.state == "active"
                    ),
                    pending_resources=frozenset(
                        resource_id for operation in pending for resource_id in operation.targets
                    ),
                    pending_scopes=frozenset(
                        operation.target
                        for operation in pending
                        if operation.kind in {"scope_create", "scope_retire", "membership"}
                    ),
                    global_publication_pending=any(
                        operation.kind == "changeset_apply"
                        and bool(operation.payload.get("profile_alias"))
                        for operation in pending
                    ),
                )
                self._snapshot = snapshot
                return snapshot
            except IndexHeadChanged:
                self._snapshot = None
                raise
            except Exception as exc:
                self._snapshot = None
                raise IndexUnavailable("current binding index unavailable") from exc
