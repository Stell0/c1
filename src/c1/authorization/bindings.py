"""Resolve current operational bindings independently of knowledge revisions."""

from __future__ import annotations

from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Operation, Scope


class Bindings:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    async def get(self, identifier: str) -> Binding | None:
        value = await self.journal.get("Binding", identifier)
        return Binding.model_validate(value) if value is not None else None

    async def scope(self, identifier: str) -> Scope | None:
        value = await self.journal.get("Scope", identifier)
        return Scope.model_validate(value) if value is not None else None

    async def pending(self, identifier: str = "", scope: str = "", *, excluding: str = "") -> bool:
        for value in await self.journal.list("Operation"):
            operation = Operation.model_validate(value)
            if operation.state != "pending" or operation.id == excluding:
                continue
            if identifier in operation.targets:
                return True
            if (
                scope
                and operation.kind in {"scope_create", "scope_retire", "membership"}
                and operation.target == scope
            ):
                return True
        return False
