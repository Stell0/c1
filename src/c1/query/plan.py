"""Authorize every provisional candidate before content fetch or evaluation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from c1.authorization.fga import FGA, FGAError, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.query.index import CurrentBindingIndex, IndexHeadChanged, IndexUnavailable

_FGA_CONCURRENCY = 16


class QueryPlanError(Exception):
    def __init__(self, status: int, code: str, reason: str) -> None:
        self.status = status
        self.code = code
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class AuthorizedPlan:
    """Only these IDs may enter retrieval, matching, joins, or ordering."""

    workflow_head: str
    readable_scopes: frozenset[str]
    authorized_ids: tuple[str, ...]
    scope_by_id: Mapping[str, str]

    def contains(self, resource_id: str) -> bool:
        return resource_id in self.authorized_ids


class AuthorizedSelection:
    def __init__(
        self,
        journal: Journal,
        fga: FGA,
        plane: AuthorizationPlane,
        *,
        index: CurrentBindingIndex | None = None,
        candidate_limit: int = 5000,
        max_readable_scopes: int = 500,
        time_budget_ms: int = 2000,
    ) -> None:
        if not 1 <= candidate_limit <= 5000:
            raise ValueError("candidate limit must be within 1..5000")
        if not 1 <= max_readable_scopes <= 500:
            raise ValueError("scope limit must be within 1..500")
        if not 1 <= time_budget_ms <= 2000:
            raise ValueError("time budget must be within 1..2000 ms")
        self.journal = journal
        self.fga = fga
        self.plane = plane
        self.index = index or CurrentBindingIndex(journal)
        self.candidate_limit = candidate_limit
        self.max_readable_scopes = max_readable_scopes
        self.time_budget_ms = time_budget_ms

    async def build(
        self,
        principal: Principal,
        *,
        scope_ids: frozenset[str] | None = None,
        candidate_ids: frozenset[str] | None = None,
        deadline: float | None = None,
    ) -> AuthorizedPlan:
        """Build from current state, including fresh per-resource M03 checks.

        The caller may supply an earlier absolute monotonic deadline so fetch
        and rendering share the same request budget. Type and text filters are
        intentionally absent here: they cannot narrow before authorization.
        """
        local_deadline = time.monotonic() + self.time_budget_ms / 1000
        effective_deadline = (
            min(local_deadline, deadline) if deadline is not None else local_deadline
        )
        if effective_deadline <= time.monotonic():
            raise QueryPlanError(503, "C1-QY-053", "time_budget")
        try:
            async with asyncio.timeout_at(effective_deadline):
                return await self._build(
                    principal, scope_ids=scope_ids, candidate_ids=candidate_ids
                )
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc

    async def finalize(
        self,
        principal: Principal,
        plan: AuthorizedPlan,
        *,
        deadline: float | None = None,
    ) -> None:
        """Recheck selected authority after content fetch, before publication."""
        local_deadline = time.monotonic() + self.time_budget_ms / 1000
        effective_deadline = (
            min(local_deadline, deadline) if deadline is not None else local_deadline
        )
        if effective_deadline <= time.monotonic():
            raise QueryPlanError(503, "C1-QY-053", "time_budget")
        try:
            async with asyncio.timeout_at(effective_deadline):
                if await self.journal.head() != plan.workflow_head:
                    raise QueryPlanError(409, "C1-QY-051", "restart_required")
                current = await self._authorize(principal, plan.authorized_ids, plan.scope_by_id)
                if current != plan.authorized_ids:
                    raise QueryPlanError(409, "C1-QY-051", "restart_required")
                if await self.journal.head() != plan.workflow_head:
                    raise QueryPlanError(409, "C1-QY-051", "restart_required")
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc
        except QueryPlanError:
            raise
        except Exception as exc:
            raise QueryPlanError(503, "C1-QY-054", "authorization_unavailable") from exc

    async def _authorize(
        self,
        principal: Principal,
        candidate_ids: tuple[str, ...],
        scope_by_id: Mapping[str, str],
    ) -> tuple[str, ...]:
        """Bulk equivalent of M03 current bound_to plus can_read checks."""
        if not candidate_ids:
            return ()
        semaphore = asyncio.Semaphore(_FGA_CONCURRENCY)

        async def batch(chunk: tuple[str, ...]) -> list[bool]:
            checks = [(principal.id, "can_read", resource_object(i)) for i in chunk]
            async with semaphore:
                try:
                    decisions = await self.fga.batch_check(checks)
                except FGAError:
                    decisions = [await self.fga.check(*check) for check in checks]
            if len(decisions) != len(chunk):
                raise IndexUnavailable("incomplete authorization decisions")
            return decisions

        async def binding(identifier: str) -> list[str]:
            async with semaphore:
                return await self.fga.bindings(resource_object(identifier))

        chunks = [candidate_ids[start : start + 50] for start in range(0, len(candidate_ids), 50)]
        async with asyncio.TaskGroup() as group:
            batch_tasks = [group.create_task(batch(chunk)) for chunk in chunks]
            binding_tasks = [group.create_task(binding(identifier)) for identifier in candidate_ids]
        batches = [task.result() for task in batch_tasks]
        bindings = [task.result() for task in binding_tasks]
        allowed = [decision for chunk in batches for decision in chunk]
        result: list[str] = []
        for identifier, is_allowed, live_binding in zip(
            candidate_ids, allowed, bindings, strict=True
        ):
            expected = [scope_object(scope_by_id[identifier])]
            if live_binding != expected:
                self.plane.audit.emit(
                    principal.id, "check", identifier, reason="inconsistent_binding"
                )
                continue
            if is_allowed:
                result.append(identifier)
        return tuple(result)

    async def _build(
        self,
        principal: Principal,
        *,
        scope_ids: frozenset[str] | None,
        candidate_ids: frozenset[str] | None,
    ) -> AuthorizedPlan:
        try:
            head = await self.journal.head()
            objects = await self.fga.list_objects(principal.id, "reader", "scope")
            if len(objects) >= self.max_readable_scopes:
                raise QueryPlanError(422, "C1-QY-050", "authorization_set_unbounded")
            readable: set[str] = set()
            for obj in objects:
                if not obj.startswith("scope:") or scope_object(obj[6:]) != obj:
                    raise ValueError("invalid scope object")
                if obj in readable:
                    raise ValueError("duplicate scope object")
                readable.add(obj)
            readable_scopes = frozenset(obj[6:] for obj in readable)
            snapshot = await self.index.snapshot(head)
            provisional = snapshot.candidates(
                readable_scopes, scope_ids=scope_ids, candidate_ids=candidate_ids
            )
            if len(provisional) > self.candidate_limit:
                raise QueryPlanError(422, "C1-QY-052", "candidate_set_too_large")
            provisional_set = set(provisional)
            provisional_scopes = {
                binding.resource_id: binding.scope_id
                for binding in snapshot.bindings
                if binding.resource_id in provisional_set
            }
            authorized = await self._authorize(principal, provisional, provisional_scopes)
            if await self.journal.head() != head:
                raise IndexHeadChanged("workflow head changed")
            authorized_set = set(authorized)
            current_scopes = {
                binding.resource_id: binding.scope_id
                for binding in snapshot.bindings
                if binding.resource_id in authorized_set
            }
            return AuthorizedPlan(
                head,
                readable_scopes,
                authorized,
                MappingProxyType(current_scopes),
            )
        except QueryPlanError:
            raise
        except IndexHeadChanged as exc:
            raise QueryPlanError(409, "C1-QY-051", "restart_required") from exc
        except Exception as exc:
            raise QueryPlanError(503, "C1-QY-054", "authorization_unavailable") from exc
