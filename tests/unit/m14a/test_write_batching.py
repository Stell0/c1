"""M14a D3: batched decisions seed the step memo with identical decisions."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from c1.authorization.models import Decision
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.changes.apply import _DecisionMemo

P = Principal(issuer_alias="local", subject="author", kind="human")


class FakeJournal:
    async def head(self) -> str:
        return "workflow:1"


class FakePlane:
    def __init__(self) -> None:
        self.journal = FakeJournal()
        self.single = 0
        self.batched: list[tuple[str, tuple[str, ...], str]] = []
        self.allowed = {"urn:a", "urn:c"}

    async def check_many(
        self, p: Any, ids: Any, relation: str, *, excluding: str = "", batch: bool = False
    ) -> dict[str, Decision]:
        self.batched.append((relation, tuple(ids), excluding))
        return {
            i: Decision(i in self.allowed, "allowed" if i in self.allowed else "denied")
            for i in ids
        }

    async def check_read(self, p: Any, identifier: str, *, excluding: str = "") -> Decision:
        self.single += 1
        return Decision(identifier in self.allowed, "single")

    async def check_operation(
        self, p: Any, op: str, identifier: str, *, excluding: str = ""
    ) -> Decision:
        self.single += 1
        return Decision(identifier in self.allowed, "single")


def test_prefetch_seeds_single_check_keys() -> None:
    async def run() -> None:
        plane = FakePlane()
        memo = _DecisionMemo(cast(AuthorizationPlane, plane))
        await memo.prefetch(P, "review", ["urn:a", "urn:b", "urn:a"], excluding="op-1")
        await memo.prefetch(P, "read", ["urn:a", "urn:c"])
        assert plane.batched == [
            ("can_review", ("urn:a", "urn:b"), "op-1"),
            ("can_read", ("urn:a", "urn:c"), ""),
        ]
        assert (await memo.check_operation(P, "review", "urn:a", excluding="op-1")).allowed
        assert not (await memo.check_operation(P, "review", "urn:b", excluding="op-1")).allowed
        assert (await memo.check_read(P, "urn:c")).allowed
        assert plane.single == 0
        # A different exclusion or relation is a different decision: computed freshly.
        await memo.check_operation(P, "review", "urn:a")
        await memo.check_operation(P, "contribute", "urn:a", excluding="op-1")
        assert plane.single == 2
        # Already decided resources are not re-batched.
        await memo.prefetch(P, "read", ["urn:a"])
        assert len(plane.batched) == 2

    asyncio.run(run())
