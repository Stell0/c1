"""Fresh, current-binding decisions; no positive permission cache."""

from __future__ import annotations

from c1.authorization.audit import Audit
from c1.authorization.bindings import Bindings
from c1.authorization.fga import FGA, FGAError, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Decision
from c1.authorization.principal import Principal


class AuthorizationPlane:
    def __init__(self, journal: Journal, fga: FGA, instance_id: str, audit: Audit) -> None:
        self.journal = journal
        self.fga = fga
        self.instance_id = instance_id
        self.audit = audit
        self.current = Bindings(journal)

    async def bindings(self, resource_id: str) -> Binding | None:
        return await self.current.get(resource_id)

    async def _resource(
        self, p: Principal, identifier: str, relation: str, prechecked: bool | None = None
    ) -> Decision:
        try:
            before = await self.journal.head()
            binding = await self.current.get(identifier)
            if binding is None or binding.state != "active":
                return Decision(False, "inactive_binding")
            scope = await self.current.scope(binding.scope_id)
            if scope is None or scope.state != "active":
                return Decision(False, "unresolved_scope")
            if await self.current.pending(identifier, binding.scope_id):
                return Decision(False, "pending_security_operation")
            obj = resource_object(identifier)
            if await self.fga.bindings(obj) != [scope_object(binding.scope_id)]:
                self.audit.emit(p.id, "check", identifier, reason="inconsistent_binding")
                return Decision(False, "inconsistent_binding")
            allowed = (
                await self.fga.check(p.id, relation, obj) if prechecked is None else prechecked
            )
            if before != await self.journal.head():
                return Decision(False, "security_revision_changed")
            return Decision(allowed, "allowed" if allowed else "permission_denied")
        except Exception:
            return Decision(False, "security_unavailable")

    async def check_read(self, p: Principal, resource_id: str) -> Decision:
        return await self._resource(p, resource_id, "can_read")

    async def check_operation(self, p: Principal, op: str, resource_id: str) -> Decision:
        relation = {
            "contribute": "can_contribute",
            "edit": "can_contribute",
            "review": "can_review",
        }.get(op)
        return (
            Decision(False, "unsupported_operation")
            if relation is None
            else await self._resource(p, resource_id, relation)
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
            scope = await self.current.scope(scope_id)
            if (
                scope is None
                or scope.state != "active"
                or await self.current.pending(scope=scope_id)
            ):
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
            if any(
                value.get("kind") == "instance_grant" and value.get("state") == "pending"
                for value in await self.journal.list("Operation")
            ):
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
        result: dict[str, Decision] = {}
        for start in range(0, len(resource_ids), 50):
            chunk = resource_ids[start : start + 50]
            try:
                before = await self.journal.head()
                try:
                    allowed = await self.fga.batch_check(
                        [(p.id, "can_read", resource_object(i)) for i in chunk]
                    )
                except FGAError:
                    # Explicit safe fallback for older/limited BatchCheck APIs.
                    allowed = [
                        await self.fga.check(p.id, "can_read", resource_object(i)) for i in chunk
                    ]
                for identifier, decision in zip(chunk, allowed, strict=True):
                    result[identifier] = await self._resource(p, identifier, "can_read", decision)
                if before != await self.journal.head():
                    for identifier in chunk:
                        result[identifier] = Decision(False, "security_revision_changed")
            except Exception:
                for identifier in chunk:
                    result[identifier] = Decision(False, "security_unavailable")
        return result
