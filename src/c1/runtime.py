"""Wire the single configured service and authorize before content selection."""

from __future__ import annotations

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
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
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


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.audit = Audit()
        self.tokens = TokenValidator(settings)
        self.registry = ProfileRegistry()
        self.knowledge = Terminus(storage_config(settings))
        self.journal = Journal(storage_config(settings, workflow=True))
        self.fga = FGA(settings.fga_url, settings.fga_token, settings.fga_store, settings.fga_model)
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
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
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
        except Exception:
            # Keep the process live and unready so an operator can recover after
            # dependencies return. No credential/backend text is logged.
            self.audit.emit(
                "system", "startup_recovery", outcome="unavailable", reason="recovery_pending"
            )

    async def close(self) -> None:
        self.operations.writer.close()
        await self.tokens.close()
        await self.fga.close()
        await self.journal.__aexit__(None, None, None)
        await self.knowledge.__aexit__(None, None, None)
        self._started = False

    async def ready(self) -> bool:
        try:
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
            if self.operations.writer.fd is None:
                return False
            return not any(
                op.get("state") == "pending" for op in await self.journal.list("Operation")
            )
        except Exception:
            return False

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
            if before != await self.journal.head():
                return None
            return record
        except Exception:
            return None
