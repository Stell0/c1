"""One writer, durable intent, and fail-closed security publication."""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from c1.authorization.audit import Audit
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGA, resource_object, scope_object
from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Decision, Operation, Scope
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.interchange import validate_records
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import Terminus

_SCOPE_ROLES = {"reader", "contributor", "creator", "reviewer", "access_admin"}
_INSTANCE_ROLES = {"schema_admin", "access_admin", "operator"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WriterGate:
    """Lifetime process ownership plus coroutine serialization."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()
        self.fd: int | None = None

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        async with self.lock:
            if self.fd is None:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(fd)
                    raise SecurityError(503, "writer_unavailable") from None
                self.fd = fd
            yield


class SecurityOperations:
    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        fga: FGA,
        plane: AuthorizationPlane,
        knowledge: Terminus,
        registry: ProfileRegistry,
        audit: Audit,
    ) -> None:
        self.settings, self.journal, self.fga, self.plane = settings, journal, fga, plane
        self.knowledge, self.registry, self.audit = knowledge, registry, audit
        self.writer = WriterGate(settings.lock_path)

    def _require(self, decision: Decision) -> None:
        if not decision.allowed:
            raise SecurityError(
                503 if decision.reason == "security_unavailable" else 403, "authorization_denied"
            )

    def _operation(self, kind: Any, actor: str, target: str, **kwargs: Any) -> Operation:
        return Operation(
            id=str(uuid4()),
            kind=kind,
            actor=actor,
            target=target,
            state="pending",
            created=_now(),
            updated=_now(),
            **kwargs,
        )

    async def _save(self, op: Operation, *entries: tuple[str, str, dict[str, Any]]) -> None:
        op.updated = _now()
        await self.journal.save_many([("Operation", op.id, op.model_dump(mode="json")), *entries])

    def _crash(self, point: str) -> None:
        if self.settings.enable_probe_routes and self.settings.crash_after == point:
            os._exit(86)

    def _public(self, op: Operation) -> dict[str, Any]:
        # Recovery payload may contain synthetic content and is never an audit
        # or security-operation API response.
        return op.model_dump(mode="json", exclude={"payload"})

    async def _scope(self, identifier: str) -> Scope:
        try:
            scope_object(identifier)
        except ValueError:
            raise SecurityError(422, "invalid_scope") from None
        scope = await self.plane.current.scope(identifier)
        if scope is None or scope.state != "active":
            raise SecurityError(404, "not_found")
        return scope

    async def create_scope(self, p: Principal, label: str, id: str | None = None) -> dict[str, Any]:
        async with self.writer.hold():
            self._require(await self.plane.check_instance(p, "access_admin"))
            identifier = id or str(uuid4())
            try:
                scope_object(identifier)
            except ValueError:
                raise SecurityError(422, "invalid_scope") from None
            if not label.strip() or len(label) > 256:
                raise SecurityError(422, "invalid_label")
            if await self.journal.get("Scope", identifier) is not None:
                raise SecurityError(409, "scope_exists")
            scope = Scope(id=identifier, label=label, state="provisioning")
            op = self._operation("scope_create", p.id, identifier)
            await self._save(op, ("Scope", identifier, scope.model_dump(mode="json")))
            await self._reconcile(op)
            return (await self._scope(identifier)).model_dump(mode="json")

    async def retire_scope(self, p: Principal, id: str) -> dict[str, Any]:
        async with self.writer.hold():
            self._require(await self.plane.check_scope(p, "access_admin", id))
            await self._scope(id)
            await self._no_dependents(id)
            op = self._operation("scope_retire", p.id, id)
            await self._save(op)
            await self._reconcile(op)
            return self._public(op)

    async def _no_dependents(self, scope: str) -> None:
        if any(value.get("scope_id") == scope for value in await self.journal.list("Binding")):
            raise SecurityError(409, "scope_has_dependents")
        if await self.fga.read(user=scope_object(scope), relation="bound_to", object="resource:"):
            raise SecurityError(409, "scope_has_dependents")

    @staticmethod
    def _member(member: str) -> None:
        if not re.fullmatch(r"(?:user:[A-Za-z0-9_.%~-]+|group:[A-Za-z0-9_-]+#member)", member):
            raise SecurityError(422, "invalid_member")

    async def membership(
        self, p: Principal, scope: str, member: str, role: str, grant: bool = True
    ) -> dict[str, Any]:
        self._member(member)
        if role not in _SCOPE_ROLES:
            raise SecurityError(422, "invalid_role")
        async with self.writer.hold():
            self._require(await self.plane.check_scope(p, "access_admin", scope))
            op = self._operation(
                "membership", p.id, scope, payload={"member": member, "role": role, "grant": grant}
            )
            await self._save(op)
            await self._reconcile(op)
            return self._public(op)

    async def instance_grant(
        self, p: Principal, member: str, role: str, grant: bool = True
    ) -> dict[str, Any]:
        self._member(member)
        if role not in _INSTANCE_ROLES:
            raise SecurityError(422, "invalid_role")
        async with self.writer.hold():
            self._require(await self.plane.check_instance(p, "access_admin"))
            op = self._operation(
                "instance_grant",
                p.id,
                self.settings.instance_id,
                payload={"member": member, "role": role, "grant": grant},
            )
            await self._save(op)
            await self._reconcile(op)
            return self._public(op)

    def _probe(self, record: NodeRecord) -> NodeRecord:
        if not self.settings.enable_probe_routes or not record.id.startswith("urn:c1:probe:"):
            raise SecurityError(404, "not_found")
        return validate_records([record], self.registry).records[0]

    @staticmethod
    def _matches(left: NodeRecord | None, right: NodeRecord) -> bool:
        """Compare exact RDF terms, independent of backend Set ordering."""
        return (
            left is not None
            and left.id == right.id
            and set(left.types) == set(right.types)
            and {key: frozenset(values) for key, values in left.properties.items() if values}
            == {key: frozenset(values) for key, values in right.properties.items() if values}
        )

    async def provision(
        self,
        p: Principal,
        record: NodeRecord,
        scope_id: str | None = None,
        inherited_from: str | None = None,
    ) -> dict[str, Any]:
        record = self._probe(record)
        async with self.writer.hold():
            if inherited_from is not None:
                parent = await self.plane.bindings(inherited_from)
                self._require(await self.plane.check_read(p, inherited_from))
                if parent is None or parent.state != "active":
                    raise SecurityError(404, "not_found")
                if scope_id is not None and scope_id != parent.scope_id:
                    raise SecurityError(422, "inheritance_scope_conflict")
                scope_id = parent.scope_id
            if scope_id is None:
                raise SecurityError(422, "scope_required")
            self._require(await self.plane.check_scope(p, "create", scope_id))
            await self._scope(scope_id)
            if await self.journal.get("Binding", record.id) is not None:
                visible = await self.plane.check_read(p, record.id)
                if not visible.allowed:
                    raise SecurityError(
                        503 if visible.reason == "security_unavailable" else 404, "not_found"
                    )
                raise SecurityError(409, "resource_exists")
            if await self.knowledge.get_record(record.id, self.registry) is not None:
                # Without a current binding this identity cannot be visible.
                raise SecurityError(404, "not_found")
            op = self._operation(
                "provision",
                p.id,
                record.id,
                to_scope=scope_id,
                targets=[record.id],
                payload={
                    "record": record.model_dump(mode="json"),
                    "base_revision": await self.knowledge.head(),
                },
            )
            binding = Binding(
                resource_id=record.id,
                scope_id=scope_id,
                state="provisioning",
                inherited_from=inherited_from,
                operation_id=op.id,
            )
            await self._save(op, ("Binding", record.id, binding.model_dump(mode="json")))
            self._crash("journal")
            await self._reconcile(op)
            return {
                "resource_id": record.id,
                "operation_id": op.id,
                "revision": op.payload["revision"],
            }

    async def _cascade(self, resource: str) -> list[Binding]:
        all_bindings = [Binding.model_validate(b) for b in await self.journal.list("Binding")]
        by_id = {b.resource_id: b for b in all_bindings}
        if resource not in by_id:
            raise SecurityError(404, "not_found")
        ids = {resource}
        while True:
            children = {b.resource_id for b in all_bindings if b.inherited_from in ids}
            extra = children - ids
            if not extra:
                break
            ids.update(extra)
            if len(ids) > 1000:
                raise SecurityError(409, "cascade_limit")
        return [by_id[i] for i in sorted(ids)]

    async def propose_rescope(
        self, p: Principal, resource_id: str, to_scope: str
    ) -> dict[str, Any]:
        async with self.writer.hold():
            targets = await self._cascade(resource_id)
            await self._scope(to_scope)
            for binding in targets:
                if binding.state != "active" or await self.plane.current.pending(
                    binding.resource_id, binding.scope_id
                ):
                    raise SecurityError(409, "resource_transitioning")
                self._require(await self.plane.check_scope(p, "access_admin", binding.scope_id))
            self._require(await self.plane.check_scope(p, "access_admin", to_scope))
            root = next(b for b in targets if b.resource_id == resource_id)
            op = self._operation(
                "rescope",
                p.id,
                resource_id,
                from_scope=root.scope_id,
                to_scope=to_scope,
                targets=[b.resource_id for b in targets],
                payload={"bindings": [b.model_dump(mode="json") for b in targets]},
            )
            op.state = "proposed"
            await self._save(op)
            self.audit.emit(
                p.id, "rescope", resource_id, "proposed", "declassification_review_required"
            )
            return self._public(op)

    async def _load_operation(self, id: str) -> Operation:
        payload = await self.journal.get("Operation", id)
        if payload is None:
            raise SecurityError(404, "not_found")
        return Operation.model_validate(payload)

    async def approve(self, p: Principal, operation_id: str) -> dict[str, Any]:
        async with self.writer.hold():
            op = await self._load_operation(operation_id)
            if op.kind != "rescope" or op.state not in {"proposed", "approved"}:
                raise SecurityError(409, "invalid_operation_state")
            self._require(await self.plane.check_scope(p, "access_admin", str(op.to_scope)))
            if self.settings.independent_review and p.id == op.actor:
                raise SecurityError(403, "independent_review_required")
            if p.id not in op.approvals:
                op.approvals.append(p.id)
            op.state = "approved"
            await self._save(op)
            self.audit.emit(p.id, "approve", op.id, "approved", "authorized")
            return self._public(op)

    async def apply(self, p: Principal, operation_id: str) -> dict[str, Any]:
        async with self.writer.hold():
            op = await self._load_operation(operation_id)
            if op.kind != "rescope" or op.state != "approved":
                raise SecurityError(409, "approval_required")
            # Both executor and original approving authorities are fresh.
            self._require(await self.plane.check_scope(p, "access_admin", str(op.to_scope)))
            current = await self._cascade(op.target)
            if [b.model_dump(mode="json") for b in current] != op.payload["bindings"]:
                raise SecurityError(409, "stale_security_operation")
            for b in current:
                self._require(await self.plane.check_scope(p, "access_admin", b.scope_id))
            if not await self._authorized(op):
                raise SecurityError(403, "authority_revoked")
            op.state = "pending"
            transitions = []
            for b in current:
                b.state, b.operation_id = "transitioning", op.id
                transitions.append(("Binding", b.resource_id, b.model_dump(mode="json")))
            await self._save(op, *transitions)
            self._crash("journal")
            await self._reconcile(op)
            return self._public(op)

    async def _authorized(self, op: Operation) -> bool:
        async def scope_check(actor: str, scope: str, role: str) -> bool:
            value = await self.plane.current.scope(scope)
            return (
                value is not None
                and value.state == "active"
                and await self.fga.check(actor, role, scope_object(scope))
            )

        if op.kind in {"scope_create", "instance_grant"}:
            return await self.fga.check(
                op.actor, "access_admin", "instance:" + self.settings.instance_id
            )
        if op.kind in {"membership", "scope_retire"}:
            return await scope_check(op.actor, op.target, "access_admin")
        if op.kind == "provision":
            scope = str(op.to_scope)
            return await scope_check(op.actor, scope, "creator") or await scope_check(
                op.actor, scope, "contributor"
            )
        if op.kind == "rescope":
            if not await scope_check(op.actor, str(op.to_scope), "access_admin"):
                return False
            for b in op.payload["bindings"]:
                if not await scope_check(op.actor, b["scope_id"], "access_admin"):
                    return False
            for actor in op.approvals:
                if (
                    not self.settings.independent_review or actor != op.actor
                ) and await scope_check(actor, str(op.to_scope), "access_admin"):
                    return True
            return False
        if op.kind == "probe_revision":
            binding = await self.plane.bindings(op.target)
            if binding is None or binding.state != "active":
                return False
            if await self.plane.current.pending(op.target, binding.scope_id, excluding=op.id):
                return False
            if await self.fga.bindings(resource_object(op.target)) != [
                scope_object(binding.scope_id)
            ]:
                return False
            return await scope_check(
                op.actor, binding.scope_id, "contributor"
            ) and await self.fga.check(op.actor, "can_contribute", resource_object(op.target))
        return False

    async def _complete(self, op: Operation, *entries: tuple[str, str, dict[str, Any]]) -> None:
        op.state = "applied"
        op.steps = list(dict.fromkeys([*op.steps, "journal", "tuple", "confirm"]))
        await self._save(op, *entries)
        self.audit.emit(op.actor, op.kind, op.target, "applied", "confirmed")

    async def _reconcile(self, op: Operation) -> None:
        if op.state != "pending":
            return
        if op.kind in {"membership", "instance_grant"} and op.payload.get("grant") is False:
            obj = (
                scope_object(op.target)
                if op.kind == "membership"
                else "instance:" + self.settings.instance_id
            )
            data = op.payload
            # Confirm an already-completed revocation without regranting its
            # initiator. This makes self-revocation crash recovery monotone:
            # no permission is introduced and current grants stay authoritative.
            entries = await self.fga.read(user=data["member"], relation=data["role"], object=obj)
            if (data["member"], data["role"], obj) not in entries:
                await self._complete(op)
                return
        if not await self._authorized(op):
            # Keep durable pending state and the publication barrier. A future
            # authorized recovery may retry; never publish after authority loss.
            raise SecurityError(503, "recovery_authority_unavailable")
        if op.kind in {"membership", "instance_grant"}:
            obj = (
                scope_object(op.target)
                if op.kind == "membership"
                else "instance:" + self.settings.instance_id
            )
            data = op.payload
            await self.fga.ensure_tuple(data["member"], data["role"], obj, grant=data["grant"])
        elif op.kind == "scope_create":
            await self.fga.ensure_tuple(
                op.actor, "access_admin", scope_object(op.target), grant=True
            )
            scope = Scope.model_validate(await self.journal.get("Scope", op.target))
            scope.state = "active"
            await self._complete(op, ("Scope", scope.id, scope.model_dump(mode="json")))
            return
        elif op.kind == "scope_retire":
            await self._no_dependents(op.target)
            scope = Scope.model_validate(await self.journal.get("Scope", op.target))
            scope.state = "retired"
            # Tombstone is durable; leftover scope membership cannot authorize a resource.
            await self._complete(op, ("Scope", scope.id, scope.model_dump(mode="json")))
            return
        elif op.kind == "provision":
            record = NodeRecord.model_validate(op.payload["record"])
            existing = await self.knowledge.get_record(record.id, self.registry)
            if existing is None:
                revision = await self.knowledge.write_records(
                    validate_records([record], self.registry),
                    self.registry,
                    expected_head=op.payload["base_revision"],
                )
                op.payload["revision"] = revision
            elif not self._matches(existing, record):
                raise SecurityError(503, "publication_content_mismatch")
            else:
                op.payload.setdefault("revision", await self.knowledge.head())
            await self._save(op)
            await self.fga.bind(resource_object(record.id), scope_object(str(op.to_scope)))
            self._crash("tuple")
            if await self.fga.bindings(resource_object(record.id)) != [
                scope_object(str(op.to_scope))
            ]:
                raise SecurityError(503, "publication_not_confirmed")
            if not self._matches(
                await self.knowledge.get_record(
                    record.id, self.registry, commit=op.payload["revision"]
                ),
                record,
            ):
                raise SecurityError(503, "publication_not_confirmed")
            self._crash("confirm")
            binding = Binding.model_validate(await self.journal.get("Binding", record.id))
            binding.state = "active"
            await self._complete(op, ("Binding", record.id, binding.model_dump(mode="json")))
            return
        elif op.kind == "rescope":
            for identifier in op.targets:
                await self.fga.bind(resource_object(identifier), scope_object(str(op.to_scope)))
            self._crash("tuple")
            for identifier in op.targets:
                if await self.fga.bindings(resource_object(identifier)) != [
                    scope_object(str(op.to_scope))
                ]:
                    raise SecurityError(503, "rescope_not_confirmed")
                if await self.knowledge.get_record(identifier, self.registry) is None:
                    raise SecurityError(503, "rescope_content_missing")
            self._crash("confirm")
            bindings = []
            for identifier in op.targets:
                binding = Binding.model_validate(await self.journal.get("Binding", identifier))
                binding.scope_id, binding.state = str(op.to_scope), "active"
                # Direct rescope stops inheritance from a parent not in this cascade.
                if identifier == op.target and binding.inherited_from not in op.targets:
                    binding.inherited_from = None
                bindings.append(("Binding", identifier, binding.model_dump(mode="json")))
            await self._complete(op, *bindings)
            return
        elif op.kind == "probe_revision":
            record = NodeRecord.model_validate(op.payload["record"])
            existing = await self.knowledge.get_record(record.id, self.registry)
            if not self._matches(existing, record):
                op.payload["revision"] = await self.knowledge.replace_records(
                    validate_records([record], self.registry),
                    self.registry,
                    expected_head=op.payload["base_revision"],
                )
            else:
                op.payload.setdefault("revision", await self.knowledge.head())
        else:
            raise SecurityError(503, "unknown_operation")
        await self._complete(op)

    async def revise_probe(
        self, p: Principal, resource_id: str, record: NodeRecord
    ) -> dict[str, Any]:
        record = self._probe(record)
        if record.id != resource_id:
            raise SecurityError(422, "resource_id_mismatch")
        async with self.writer.hold():
            self._require(await self.plane.check_operation(p, "contribute", resource_id))
            op = self._operation(
                "probe_revision",
                p.id,
                resource_id,
                targets=[resource_id],
                payload={
                    "record": record.model_dump(mode="json"),
                    "base_revision": await self.knowledge.head(),
                },
            )
            await self._save(op)
            await self._reconcile(op)
            return {"resource_id": resource_id, "revision": op.payload["revision"]}

    async def get_operation(self, p: Principal, id: str) -> dict[str, Any]:
        op = await self._load_operation(id)
        if op.actor != p.id:
            if op.to_scope:
                self._require(await self.plane.check_scope(p, "access_admin", op.to_scope))
            else:
                self._require(await self.plane.check_instance(p, "access_admin"))
        return self._public(op)

    async def recover(self) -> None:
        async with self.writer.hold():
            entries = sorted(
                await self.journal.list("Operation"), key=lambda o: str(o.get("created", ""))
            )
            for entry in entries:
                op = Operation.model_validate(entry)
                if op.state == "pending" and op.kind != "changeset_apply":
                    await self._reconcile(op)
