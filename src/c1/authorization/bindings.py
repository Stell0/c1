"""Resolve current operational bindings independently of knowledge revisions."""

from __future__ import annotations

from c1.authorization.journal import Journal
from c1.authorization.models import Binding, Scope


class Bindings:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    async def get(self, identifier: str) -> Binding | None:
        value = (await self.journal.view()).binding(identifier)
        return value.model_copy(deep=True) if value is not None else None

    async def scope(self, identifier: str) -> Scope | None:
        value = (await self.journal.view()).scope(identifier)
        return value.model_copy(deep=True) if value is not None else None

    async def pending(self, identifier: str = "", scope: str = "", *, excluding: str = "") -> bool:
        return (await self.journal.view()).pending(identifier, scope, excluding=excluding)
