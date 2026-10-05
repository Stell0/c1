"""Authorize every provisional candidate before content fetch or evaluation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType

from c1.authorization.fga import FGA, FGAError, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane, bound_to_many
from c1.authorization.principal import Principal
from c1.query.index import CurrentBindingIndex, IndexHeadChanged, IndexUnavailable

_FGA_CONCURRENCY = 16


class QueryPlanError(Exception):
    def __init__(self, status: int, code: str, reason: str) -> None:
        self.status = status
        self.code = code
        self.reason = reason
        super().__init__(reason)


# Store-wide binding count for the current request's authorization pass; it
# only sizes the exact `bound_to` source (M09a D4) and never grants anything.
_BINDING_COUNT: ContextVar[int] = ContextVar("c1_binding_count", default=0)


@dataclass(frozen=True, slots=True)
class AuthorizedPlan:
    """Only these IDs may enter retrieval, matching, joins, or ordering."""

    workflow_head: str
    readable_scopes: frozenset[str]
    authorized_ids: tuple[str, ...]
    scope_by_id: Mapping[str, str]
    history_manifest: bytes | None = None
    # Current journal bindings when the plan was built; sizes the binding
    # source for finalize (M09a D4). Zero means one read per resource.
    binding_count: int = 0
    # M14a B1: complete storage-class hints for journaled resources (index).
    class_hints: Mapping[str, frozenset[str]] = field(default_factory=dict)

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
        time_budget_ms: int = 10000,
    ) -> None:
        if not 1 <= candidate_limit <= 5000:
            raise ValueError("candidate limit must be within 1..5000")
        if not 1 <= max_readable_scopes <= 500:
            raise ValueError("scope limit must be within 1..500")
        if not 1 <= time_budget_ms <= 30000:
            raise ValueError("time budget must be within 1..30000 ms")
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
                _BINDING_COUNT.set(plan.binding_count)
                authorization = asyncio.create_task(
                    self._authorize(principal, plan.authorized_ids, plan.scope_by_id)
                )
                try:
                    if await self.journal.head() != plan.workflow_head:
                        raise QueryPlanError(409, "C1-QY-051", "restart_required")
                    current = await authorization
                    if current != plan.authorized_ids:
                        raise QueryPlanError(409, "C1-QY-051", "restart_required")
                    if await self.journal.head() != plan.workflow_head:
                        raise QueryPlanError(409, "C1-QY-051", "restart_required")
                except BaseException:
                    if not authorization.done():
                        authorization.cancel()
                    await asyncio.gather(authorization, return_exceptions=True)
                    raise
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc
        except QueryPlanError:
            raise
        except Exception as exc:
            raise QueryPlanError(503, "C1-QY-054", "authorization_unavailable") from exc

    async def finalize_after(
        self,
        principal: Principal,
        plan: AuthorizedPlan,
        precondition: Callable[[], Awaitable[None]],
        *,
        deadline: float | None = None,
    ) -> None:
        """Overlap a publication precondition, retaining a final security barrier.

        This internal factory is never client configuration. Knowledge-head
        equality may overlap fresh authorization and the first workflow read;
        the last workflow read starts only after all three checks succeed.
        Precondition errors keep their caller's error semantics and priority.
        """
        local_deadline = time.monotonic() + self.time_budget_ms / 1000
        effective_deadline = (
            min(local_deadline, deadline) if deadline is not None else local_deadline
        )
        if effective_deadline <= time.monotonic():
            raise QueryPlanError(503, "C1-QY-053", "time_budget")
        precondition_done = False

        async def check_precondition() -> None:
            await precondition()

        try:
            async with asyncio.timeout_at(effective_deadline):
                publication = asyncio.create_task(check_precondition())
                _BINDING_COUNT.set(plan.binding_count)
                authorization = asyncio.create_task(
                    self._authorize(principal, plan.authorized_ids, plan.scope_by_id)
                )
                initial_head = asyncio.create_task(self.journal.head())
                try:
                    # Historical head mismatch/errors precede security errors,
                    # even if an authorization task has already failed.
                    await publication
                    precondition_done = True
                    try:
                        if await initial_head != plan.workflow_head:
                            raise QueryPlanError(409, "C1-QY-051", "restart_required")
                        if await authorization != plan.authorized_ids:
                            raise QueryPlanError(409, "C1-QY-051", "restart_required")
                        if await self.journal.head() != plan.workflow_head:
                            raise QueryPlanError(409, "C1-QY-051", "restart_required")
                    except TimeoutError:
                        raise
                    except QueryPlanError:
                        raise
                    except Exception as exc:
                        raise QueryPlanError(503, "C1-QY-054", "authorization_unavailable") from exc
                finally:
                    for task in (publication, authorization, initial_head):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        publication, authorization, initial_head, return_exceptions=True
                    )
        except TimeoutError as exc:
            if not precondition_done:
                raise
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc

    def _readable_scopes(self, objects: list[str]) -> frozenset[str]:
        if len(objects) >= self.max_readable_scopes:
            raise QueryPlanError(422, "C1-QY-050", "authorization_set_unbounded")
        readable: set[str] = set()
        for obj in objects:
            if not obj.startswith("scope:") or scope_object(obj[6:]) != obj:
                raise ValueError("invalid scope object")
            if obj in readable:
                raise ValueError("duplicate scope object")
            readable.add(obj)
        return frozenset(obj[6:] for obj in readable)

    async def _authorize(
        self,
        principal: Principal,
        candidate_ids: tuple[str, ...],
        scope_by_id: Mapping[str, str],
        readable_scopes: frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        """Bulk equivalent of M03 current bound_to plus can_read checks.

        M14a (ADR-0025): the pinned model defines `resource#can_read` as exactly
        `reader from bound_to` (`READ_MODEL_SHAPE`, verified at startup and by
        tests). A candidate whose live `bound_to` tuples are exactly its journal
        scope is readable if and only if that scope is among the principal's
        live readable scopes. Both inputs are read freshly, with higher
        consistency, on every call; the decision is derived locally instead of
        one Check per resource. `finalize` passes no scopes and reads them again.
        """
        if not candidate_ids:
            return ()
        if not getattr(self.fga, "read_model_verified", False):
            return await self._authorize_by_checks(principal, candidate_ids, scope_by_id)

        async def live_scopes() -> frozenset[str]:
            if readable_scopes is not None:
                return readable_scopes
            return self._readable_scopes(
                await self.fga.list_objects(principal.id, "reader", "scope")
            )

        async def live_bindings() -> dict[str, list[str]]:
            # One exact source for every candidate's live tuples (M09a D4).
            return await bound_to_many(
                self.fga,
                [resource_object(identifier) for identifier in candidate_ids],
                binding_count=_BINDING_COUNT.get(),
            )

        async with asyncio.TaskGroup() as group:
            scopes_task = group.create_task(live_scopes())
            bindings_task = group.create_task(live_bindings())
        readable = scopes_task.result()
        live = bindings_task.result()
        result: list[str] = []
        for identifier in candidate_ids:
            scope = scope_by_id[identifier]
            if live[resource_object(identifier)] != [scope_object(scope)]:
                self.plane.audit.emit(
                    principal.id, "check", identifier, reason="inconsistent_binding"
                )
                continue
            if scope in readable:
                result.append(identifier)
        return tuple(result)

    async def _authorize_by_checks(
        self,
        principal: Principal,
        candidate_ids: tuple[str, ...],
        scope_by_id: Mapping[str, str],
    ) -> tuple[str, ...]:
        """M09a: one fresh `can_read` Check per candidate (unverified model shape)."""
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

        async def live_bindings() -> dict[str, list[str]]:
            return await bound_to_many(
                self.fga,
                [resource_object(identifier) for identifier in candidate_ids],
                binding_count=_BINDING_COUNT.get(),
            )

        chunks = [candidate_ids[start : start + 50] for start in range(0, len(candidate_ids), 50)]
        async with asyncio.TaskGroup() as group:
            batch_tasks = [group.create_task(batch(chunk)) for chunk in chunks]
            bindings_task = group.create_task(live_bindings())
        allowed = [decision for task in batch_tasks for decision in task.result()]
        live = bindings_task.result()
        result: list[str] = []
        for identifier, is_allowed in zip(candidate_ids, allowed, strict=True):
            if live[resource_object(identifier)] != [scope_object(scope_by_id[identifier])]:
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
            try:
                async with asyncio.TaskGroup() as group:
                    objects_task = group.create_task(
                        self.fga.list_objects(principal.id, "reader", "scope")
                    )
                    snapshot_task = group.create_task(self.index._prepare_after_head(head))
            except ExceptionGroup as exc:
                # Cold structural failures must not publish an error from a
                # changed workflow epoch merely because validation ran early.
                if exc.subgroup(IndexUnavailable) is not None and await self.journal.head() != head:
                    raise QueryPlanError(409, "C1-QY-051", "restart_required") from None
                raise
            objects = objects_task.result()
            prepared = snapshot_task.result()
            snapshot = prepared.snapshot
            try:
                readable_scopes = self._readable_scopes(objects)
                provisional = snapshot.candidates(
                    readable_scopes, scope_ids=scope_ids, candidate_ids=candidate_ids
                )
                if len(provisional) > self.candidate_limit:
                    raise QueryPlanError(422, "C1-QY-052", "candidate_set_too_large")
            except (QueryPlanError, IndexUnavailable, ValueError):
                # Preserve the bounds without launching oversized FGA work,
                # and retain exact-head priority for candidate-derived errors.
                if await self.journal.head() != head:
                    raise IndexHeadChanged("workflow head changed") from None
                raise
            provisional_set = set(provisional)
            provisional_scopes = {
                binding.resource_id: binding.scope_id
                for binding in snapshot.bindings
                if binding.resource_id in provisional_set
            }
            _BINDING_COUNT.set(len(snapshot.bindings))
            authorized = await self._authorize(
                principal, provisional, provisional_scopes, readable_scopes
            )
            if await self.journal.head() != head:
                raise IndexHeadChanged("workflow head changed")
            self.index._publish_verified(prepared)
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
                snapshot.history_manifest,
                len(snapshot.bindings),
                snapshot.class_hints,
            )
        except QueryPlanError:
            raise
        except IndexHeadChanged as exc:
            raise QueryPlanError(409, "C1-QY-051", "restart_required") from exc
        except Exception as exc:
            raise QueryPlanError(503, "C1-QY-054", "authorization_unavailable") from exc
