"""Fresh, current-binding decisions; no positive permission cache."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence

from c1 import roundtrips
from c1.authorization.audit import Audit
from c1.authorization.bindings import Bindings
from c1.authorization.fga import FGA, FGAError, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Decision
from c1.authorization.principal import Principal

_READ_CONCURRENCY = 16


def use_scan(binding_count: int, requested: int) -> bool:
    """Scan the store only when it takes fewer sequential round trips (M09a D4).

    Per-object reads run `_READ_CONCURRENCY` at a time; scan pages are
    sequential. The journal's binding count estimates the store's `bound_to`
    tuples; the 10% margin and one extra page cover other tuple kinds.
    """
    pages = math.ceil(binding_count * 1.1 / 100) + 1
    return pages < math.ceil(requested / _READ_CONCURRENCY)


@roundtrips.phased("fga.binding_source")
async def bound_to_many(
    fga: FGA, objects: Sequence[str], *, binding_count: int
) -> dict[str, list[str]]:
    """Live `bound_to` users for each resource object, from one exact source.

    The whole-store scan is used only when it needs fewer requests than one
    read per object (M09a D4); both strategies return the same multisets.
    """
    if not objects:
        return {}
    if use_scan(binding_count, len(objects)):
        scanned = await fga.scan_bindings()
        return {obj: scanned.get(obj, []) for obj in objects}
    semaphore = asyncio.Semaphore(_READ_CONCURRENCY)

    async def one(obj: str) -> list[str]:
        async with semaphore:
            return await fga.bindings(obj)

    values = await asyncio.gather(*(one(obj) for obj in objects))
    return dict(zip(objects, values, strict=True))


class AuthorizationPlane:
    def __init__(self, journal: Journal, fga: FGA, instance_id: str, audit: Audit) -> None:
        self.journal = journal
        self.fga = fga
        self.instance_id = instance_id
        self.audit = audit
        self.current = Bindings(journal)

    async def bindings(self, resource_id: str) -> Binding | None:
        return await self.current.get(resource_id)

    async def bound_to_many(
        self, objects: Sequence[str], *, binding_count: int
    ) -> dict[str, list[str]]:
        return await bound_to_many(self.fga, objects, binding_count=binding_count)

    @roundtrips.phased("plane.check_many")
    async def check_many(
        self,
        p: Principal,
        identifiers: Sequence[str],
        relation: str,
        prechecked: Mapping[str, bool] | None = None,
        *,
        excluding: str = "",
        batch: bool = False,
    ) -> dict[str, Decision]:
        """Fresh current-binding decisions for several resources (ADR-0009 rules).

        Each resource needs an active binding and scope, no pending operation,
        exactly one matching live `bound_to` tuple, and a fresh permission
        check. One security view, one binding source and BatchCheck replace
        per-resource round trips; every decision equals the single-resource one.
        """
        ids = list(dict.fromkeys(identifiers))
        try:
            before = await self.journal.head()
            view = await self.journal.view()
            if view.version != before:
                return {i: Decision(False, "security_revision_changed") for i in ids}
            result: dict[str, Decision] = {}
            expected: dict[str, str] = {}
            for identifier in ids:
                binding = view.binding(identifier)
                if binding is None or binding.state != "active":
                    result[identifier] = Decision(False, "inactive_binding")
                    continue
                scope = view.scope(binding.scope_id)
                if scope is None or scope.state != "active":
                    result[identifier] = Decision(False, "unresolved_scope")
                    continue
                if view.pending(identifier, binding.scope_id, excluding=excluding):
                    result[identifier] = Decision(False, "pending_security_operation")
                    continue
                expected[identifier] = binding.scope_id
            live = await self.bound_to_many(
                [resource_object(i) for i in expected], binding_count=len(view.bindings)
            )
            consistent: list[str] = []
            for identifier, scope_id in expected.items():
                if live[resource_object(identifier)] != [scope_object(scope_id)]:
                    self.audit.emit(p.id, "check", identifier, reason="inconsistent_binding")
                    result[identifier] = Decision(False, "inconsistent_binding")
                else:
                    consistent.append(identifier)
            allowed = await self._permissions(p, relation, consistent, prechecked, batch=batch)
            for identifier in consistent:
                result[identifier] = Decision(
                    allowed[identifier], "allowed" if allowed[identifier] else "permission_denied"
                )
            if before != await self.journal.head():
                return {i: Decision(False, "security_revision_changed") for i in ids}
            return {i: result[i] for i in ids}
        except Exception:
            return {i: Decision(False, "security_unavailable") for i in ids}

    async def _permissions(
        self,
        p: Principal,
        relation: str,
        identifiers: list[str],
        prechecked: Mapping[str, bool] | None,
        *,
        batch: bool = False,
    ) -> dict[str, bool]:
        result = {i: prechecked[i] for i in identifiers if prechecked and i in prechecked}
        pending = [i for i in identifiers if i not in result]
        for start in range(0, len(pending), 50):
            chunk = pending[start : start + 50]
            if len(chunk) == 1 and not batch:
                values = [await self.fga.check(p.id, relation, resource_object(chunk[0]))]
            else:
                try:
                    values = await self.fga.batch_check(
                        [(p.id, relation, resource_object(i)) for i in chunk]
                    )
                except FGAError:
                    # Explicit safe fallback: sequential fresh checks (ADR-0009).
                    values = [
                        await self.fga.check(p.id, relation, resource_object(i)) for i in chunk
                    ]
            if len(values) != len(chunk):
                raise FGAError("incomplete authorization decisions")
            result.update(zip(chunk, values, strict=True))
        return result

    async def _resource(
        self,
        p: Principal,
        identifier: str,
        relation: str,
        prechecked: bool | None = None,
        *,
        excluding: str = "",
    ) -> Decision:
        decisions = await self.check_many(
            p,
            [identifier],
            relation,
            None if prechecked is None else {identifier: prechecked},
            excluding=excluding,
        )
        return decisions[identifier]

    async def check_read(self, p: Principal, resource_id: str, *, excluding: str = "") -> Decision:
        return await self._resource(p, resource_id, "can_read", excluding=excluding)

    async def check_operation(
        self, p: Principal, op: str, resource_id: str, *, excluding: str = ""
    ) -> Decision:
        relation = {
            "contribute": "can_contribute",
            "edit": "can_contribute",
            "review": "can_review",
        }.get(op)
        return (
            Decision(False, "unsupported_operation")
            if relation is None
            else await self._resource(p, resource_id, relation, excluding=excluding)
        )

    async def check_scope(self, p: Principal, op: str, scope_id: str) -> Decision:
        roles = {
            "create": ("creator", "contributor"),
            "read": ("reader",),
            "review": ("reviewer",),
            "contribute": ("contributor",),
            "access_admin": ("access_admin",),
        }.get(op)
        if roles is None:
            return Decision(False, "unsupported_operation")
        try:
            before = await self.journal.head()
            view = await self.journal.view()
            if view.version != before:
                return Decision(False, "security_revision_changed")
            scope = view.scope(scope_id)
            if scope is None or scope.state != "active" or view.pending(scope=scope_id):
                return Decision(False, "inactive_scope")
            allowed = False
            for role in roles:
                allowed = await self.fga.check(p.id, role, scope_object(scope_id)) or allowed
            if before != await self.journal.head():
                return Decision(False, "security_revision_changed")
            return Decision(allowed, "allowed" if allowed else "permission_denied")
        except Exception:
            return Decision(False, "security_unavailable")

    async def check_instance(self, p: Principal, op: str) -> Decision:
        if op not in {"access_admin", "schema_admin", "operator"}:
            return Decision(False, "unsupported_operation")
        try:
            before = await self.journal.head()
            view = await self.journal.view()
            if view.version != before:
                return Decision(False, "security_revision_changed")
            if view.pending_instance_grant:
                return Decision(False, "pending_security_operation")
            allowed = await self.fga.check(p.id, op, "instance:" + self.instance_id)
            if before != await self.journal.head():
                return Decision(False, "security_revision_changed")
            return Decision(allowed, "allowed" if allowed else "permission_denied")
        except FGAError:
            return Decision(False, "security_unavailable")
        except Exception:
            return Decision(False, "security_unavailable")

    async def batch_read(self, p: Principal, resource_ids: list[str]) -> dict[str, Decision]:
        return await self.check_many(p, resource_ids, "can_read", batch=True)
