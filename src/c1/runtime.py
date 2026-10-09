"""Wire the single configured service and authorize before content selection."""

from __future__ import annotations

import time

from c1.authorization.audit import Audit
from c1.authorization.fga import FGA
from c1.authorization.journal import Journal
from c1.authorization.operations import SecurityOperations
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.authorization.tokens import TokenValidator
from c1.changes.apply import ChangeService
from c1.changes.profiles import detect_installed_registry
from c1.config import Settings
from c1.context.errors import ContextError
from c1.context.profiles import ContextProfileCatalog
from c1.context.service import ContextService
from c1.documents.service import DocumentsService
from c1.model.diagnostics import ProfileError
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, RDF
from c1.model.references import is_independent_reference, required_class_references
from c1.query.service import QueryService
from c1.software.service import SoftwareService
from c1.storage.schema import assert_installed_profiles
from c1.storage.terminus import StorageConfig, Terminus


def storage_config(settings: Settings, *, workflow: bool = False) -> StorageConfig:
    return StorageConfig(
        url=settings.terminus_url,
        password=settings.terminus_password,
        organization=settings.organization,
        database=settings.workflow_database if workflow else settings.knowledge_database,
        instance_base=settings.instance_base,
    )


def restore_guarded(records: list[dict[str, object]]) -> bool:
    """True while any disaster-recovery guard has not been explicitly released."""
    return any(r.get("type") == "guard" and r.get("released") is not True for r in records)


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.audit = Audit()
        self.tokens = TokenValidator(settings)
        self.registry = ProfileRegistry()
        self.knowledge = Terminus(storage_config(settings))
        self.journal = Journal(storage_config(settings, workflow=True))
        self.fga = FGA(
            settings.fga_url,
            settings.fga_token,
            settings.fga_store,
            settings.fga_model,
            timeout=settings.backend_timeout_s,
        )
        self.fga.read_concurrency = settings.fga_read_concurrency
        self.plane = AuthorizationPlane(self.journal, self.fga, settings.instance_id, self.audit)
        self.operations = SecurityOperations(
            settings, self.journal, self.fga, self.plane, self.knowledge, self.registry, self.audit
        )
        self.changes = ChangeService(
            settings,
            self.journal,
            self.knowledge,
            self.registry,
            self.plane,
            self.fga,
            self.operations.writer,
            self.audit,
        )
        self.query = QueryService(self)
        self.documents = DocumentsService(self)
        try:
            self.context_profiles: ContextProfileCatalog | None = ContextProfileCatalog()
        except ProfileError:
            self.context_profiles = None
        self.context = ContextService(self)
        self.software = SoftwareService(self)
        self._started = False
        # M13 D8: an unreleased disaster-recovery guard keeps the API unready.
        # It is read once at startup; releasing it requires a restart.
        self.guarded = False
        self._enrollment_verified = settings.initialization_file is None
        self._identity_verified = False
        self._legacy_reference = False

    def context_catalog(self) -> ContextProfileCatalog:
        """Validate trusted data again; changed definitions require a restart."""
        try:
            current = ContextProfileCatalog()
        except ProfileError as exc:
            raise ContextError(503, "C1-CX-002", "context_catalog_unavailable") from exc
        if self.context_profiles is None:
            self.context_profiles = current
        elif current.catalog() != self.context_profiles.catalog():
            raise ContextError(503, "C1-CX-002", "context_catalog_changed")
        return self.context_profiles

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            # M14b D4: move ID-only journal kinds before anything reads them.
            await self.journal.migrate_records()
            await self.verify_identity()
            if not self._identity_verified:
                return
            await self.operations.recover()
            try:
                self.registry = await detect_installed_registry(self.knowledge)
            except Exception:
                # A half-installed schema needs the ChangeSet recovery path.
                pass
            self.operations.registry = self.registry
            self.changes.registry = self.registry
            self.changes.history_service.registry = self.registry
            await self.changes.recover()
            self.registry = await detect_installed_registry(self.knowledge)
            self.operations.registry = self.registry
            self.changes.registry = self.registry
            self.changes.history_service.registry = self.registry
            # M14a: verify the authorization model's read shape once at startup.
            await self.fga.ready()
            # M14b D3: the finalize shortcut only with an immediate change log.
            await self.fga.verify_change_log()
        except Exception:
            # Keep the process live and unready so an operator can recover after
            # dependencies return. No credential/backend text is logged.
            self.audit.emit(
                "system", "startup_recovery", outcome="unavailable", reason="recovery_pending"
            )

    async def verify_identity(self) -> None:
        """Verify namespace/enrollment and load restore guards without write recovery."""
        self._identity_verified = False
        self.guarded = restore_guarded(await self.journal.list("Restore"))
        from c1.admin.initialization import identity

        binding = await self.journal.get("Restore", "application-identity")
        self._legacy_reference = bool(
            binding is None
            and self.settings.identity_mode == "reference"
            and (
                self.settings.initialization_file is None
                or not self.settings.initialization_file.exists()
            )
        )
        if self._legacy_reference:
            self._enrollment_verified = True
        self._identity_verified = (
            binding is None and self.settings.identity_mode == "reference"
        ) or bool(
            binding
            and binding.get("identity") == identity(self.settings)
            and binding.get("fga_store") == self.settings.fga_store
            and binding.get("fga_model") == self.settings.fga_model
        )
        if self.settings.initialization_file is not None and not self._legacy_reference:
            from c1.admin.initialization import checked

            state = checked(self.settings)
            receipt = await self.journal.get("Restore", "initial-enrollment")
            self._enrollment_verified = bool(
                state
                and state.get("state") == "complete"
                and receipt
                and receipt.get("principal") == state.get("administrator")
            )

    async def close(self) -> None:
        self.operations.writer.close()
        await self.tokens.close()
        await self.fga.close()
        await self.journal.__aexit__(None, None, None)
        await self.knowledge.__aexit__(None, None, None)
        self._started = False

    async def ready(self) -> bool:
        if self.guarded or self.enrollment_pending():
            return False
        try:
            self.context_catalog()
            if (
                not await self.tokens.ready()
                or not await self.fga.ready()
                or not await self.journal.ready()
            ):
                return False
            installed = await detect_installed_registry(self.knowledge)
            if set(installed.profiles) != set(self.registry.profiles):
                return False
            await assert_installed_profiles(self.knowledge, self.registry)
            if self.settings.identity_mode == "external":
                from c1.admin.internal import _consistency

                if not (await _consistency(self)).get("consistent"):
                    return False
            if self.operations.writer.fd is None:
                return False
            return not any(
                op.get("state") == "pending" for op in await self.journal.list("Operation")
            )
        except Exception:
            return False

    def enrollment_pending(self) -> bool:
        from c1.admin.initialization import guarded

        return (
            not self._identity_verified
            or not self._enrollment_verified
            or (not self._legacy_reference and guarded(self.settings))
        )

    async def setup_identity(self, principal: Principal) -> dict[str, object]:
        from c1.admin.initialization import InitializationError, checked

        state = None if self._legacy_reference else checked(self.settings)
        pending = state is not None and state.get("state") != "complete"
        if principal.kind != "human":
            raise InitializationError("human_browser_identity_required")
        if pending:
            assert state is not None
            approval = state.get("approval", {})
            if (
                state.get("state") not in {"approved", "enrolling"}
                or approval.get("issuer") != self.settings.issuer
                or approval.get("subject") != principal.subject
                or approval.get("expires_at", 0) <= time.time()
            ):
                raise InitializationError("enrollment_not_approved")
        return {"subject": principal.subject, "kind": principal.kind, "enrollment_pending": pending}

    async def confirm_enrollment(self, principal: Principal) -> None:
        from c1.admin.initialization import InitializationError, checked, lock, save
        from c1.admin.internal import _consistency

        path = self.settings.initialization_file
        if path is None:
            raise InitializationError("enrollment_not_available")
        async with self.operations.writer.hold():
            with lock(path):
                await self.setup_identity(principal)
                state = checked(self.settings)
                if state is None or state.get("state") == "complete":
                    raise InitializationError("enrollment_not_available")
                state["state"] = "enrolling"
                save(path, state)
                obj = "instance:" + self.settings.instance_id
                for relation in ("access_admin", "schema_admin"):
                    await self.fga.ensure_tuple(principal.id, relation, obj, grant=True)
                result = await _consistency(self)
                if not result.get("consistent") or not await self.tokens.ready():
                    raise InitializationError("enrollment_consistency_unavailable")
                if not all(
                    [
                        await self.fga.check(principal.id, relation, obj)
                        for relation in ("access_admin", "schema_admin")
                    ]
                ):
                    raise InitializationError("enrollment_grants_unavailable")
                await assert_installed_profiles(self.knowledge, self.registry)
                state["state"] = "complete"
                state["administrator"] = principal.id
                state["enrolled_at"] = time.time()
                # Durable audit before releasing the local guard.
                await self.journal.save_many(
                    [
                        (
                            "Restore",
                            "initial-enrollment",
                            {
                                "type": "enrollment",
                                "principal": principal.id,
                                "operator": state["approval"]["operator"],
                                "recorded_at": state["enrolled_at"],
                            },
                        )
                    ]
                )
                save(path, state)
                self._enrollment_verified = True

    async def read(
        self, principal: Principal, id: str, revision: str | None = None
    ) -> NodeRecord | None:
        try:
            if any(
                value.get("kind") == "changeset_apply"
                and value.get("state") == "pending"
                and value.get("payload", {}).get("profile_alias")
                for value in await self.journal.list("Operation")
            ):
                return None
            before = await self.journal.head()
            if not (await self.plane.check_read(principal, id)).allowed:
                return None
            record = await self.knowledge.get_record(id, self.registry, commit=revision)
            if record is None or not (await self.plane.check_read(principal, id)).allowed:
                return None
            references: list[str] = []
            if "http://www.w3.org/2004/02/skos/core#Concept" in record.types:
                scheme = record.properties.get("http://www.w3.org/2004/02/skos/core#inScheme", [])
                if len(scheme) != 1 or not isinstance(scheme[0], str):
                    return None
                references.append(scheme[0])
            elif C1 + "Assertion" in record.types:
                claim_predicate = next(
                    (
                        value
                        for value in record.properties.get(RDF + "predicate", ())
                        if isinstance(value, str)
                    ),
                    None,
                )
                definition = (
                    self.registry.predicates.get(claim_predicate)
                    if claim_predicate is not None
                    else None
                )
                relation = definition is not None and any(
                    item in self.registry.classes for item in definition.ranges
                )
                references.extend(
                    value
                    for predicate in (RDF + "subject", RDF + "object")
                    for value in record.properties.get(predicate, ())
                    if isinstance(value, str)
                    and (
                        predicate == RDF + "subject"
                        or relation
                        or value.startswith(self.settings.instance_base)
                    )
                )
                references.extend(
                    value
                    for value in record.properties.get(C1 + "validDuring", ())
                    if isinstance(value, str)
                )
            elif C1 + "Evidence" in record.types:
                references.extend(
                    value
                    for predicate in (
                        C1 + "assertionRef",
                        "http://www.w3.org/ns/oa#hasSource",
                    )
                    for value in record.properties.get(predicate, ())
                    if isinstance(value, str)
                )
            elif C1 + "TimeInterval" in record.types:
                references.extend(
                    value
                    for predicate in (
                        "http://www.w3.org/2006/time#hasBeginning",
                        "http://www.w3.org/2006/time#hasEnd",
                    )
                    for value in record.properties.get(predicate, ())
                    if isinstance(value, str)
                )
            elif C1 + "ResolutionRecord" in record.types:
                references.extend(
                    value
                    for value in record.properties.get(C1 + "candidate", ())
                    if isinstance(value, str)
                )
            elif "urn:c1:ns:identity#Redirect" in record.types:
                references.extend(
                    value
                    for part in ("from", "to", "resolution")
                    for value in record.properties.get("urn:c1:ns:identity#" + part, ())
                    if isinstance(value, str)
                )
            references.extend(required_class_references(record, self.registry))
            for reference in references:
                if not (await self.plane.check_read(principal, reference)).allowed:
                    return None
            visible_refs: set[str] = set(references)
            for predicate, values in record.properties.items():
                if not is_independent_reference(predicate, self.registry):
                    continue
                for value in values:
                    if isinstance(value, str) and value not in visible_refs:
                        decision = await self.plane.check_read(principal, value)
                        if decision.reason == "security_unavailable":
                            return None
                        if decision.allowed:
                            visible_refs.add(value)
            record = record.model_copy(
                update={
                    "properties": {
                        predicate: visible_values
                        for predicate, values in record.properties.items()
                        if (
                            visible_values := [
                                value
                                for value in values
                                if not isinstance(value, str)
                                or not is_independent_reference(predicate, self.registry)
                                or value in visible_refs
                            ]
                        )
                    }
                }
            )
            if before != await self.journal.head():
                return None
            return record
        except Exception:
            return None
