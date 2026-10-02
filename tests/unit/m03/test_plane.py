"""Current binding revisions and writer ownership fail closed."""

from __future__ import annotations

import asyncio
import multiprocessing
from pathlib import Path
from typing import Any, cast

from c1.authorization.audit import Audit
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGA, scope_object
from c1.authorization.journal import Journal
from c1.authorization.operations import WriterGate
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.authorization.view import SecurityView
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.runtime import Runtime
from c1.storage.terminus import Terminus

_RESOURCE = "urn:c1:probe:entity-unit"
_PRINCIPAL = Principal("c1-dev", "alice", "human")


class FakeJournal:
    revision = "branch:old"

    async def head(self) -> str:
        return self.revision

    async def get(self, kind: str, key: str) -> dict[str, Any] | None:
        if kind == "Binding" and key == _RESOURCE:
            return {
                "resource_id": key,
                "scope_id": "restricted",
                "state": "active",
                "inherited_from": None,
                "operation_id": "op-1",
            }
        if kind == "Scope" and key == "restricted":
            return {"id": key, "label": "Restricted", "state": "active"}
        return None

    async def list(self, kind: str) -> list[dict[str, Any]]:
        return []

    async def view(self) -> SecurityView:
        """The same binding and scope as `get`, at the current fake revision."""
        entries = [
            (kind, key, payload)
            for kind, key in (("Binding", _RESOURCE), ("Scope", "restricted"))
            if (payload := await self.get(kind, key)) is not None
        ]
        return SecurityView.build(self.revision, entries)


class FakeFGA:
    def __init__(self, journal: FakeJournal, *, mutate_on_check: bool = False) -> None:
        self.journal = journal
        self.mutate_on_check = mutate_on_check
        self.checked = False

    async def bindings(self, _resource: str) -> list[str]:
        return [scope_object("restricted")]

    async def check(self, _principal: str, _relation: str, _object: str) -> bool:
        self.checked = True
        if self.mutate_on_check:
            self.journal.revision = "branch:new"
        return True

    async def batch_check(self, checks: list[tuple[str, str, str]]) -> list[bool]:
        self.journal.revision = "branch:new"
        return [True for _ in checks]


def _plane(journal: FakeJournal, fga: FakeFGA) -> AuthorizationPlane:
    return AuthorizationPlane(cast(Journal, journal), cast(FGA, fga), "unit", Audit())


def test_resource_check_denies_when_binding_revision_changes_midcheck() -> None:
    async def run() -> None:
        journal = FakeJournal()
        fga = FakeFGA(journal, mutate_on_check=True)
        decision = await _plane(journal, fga).check_read(_PRINCIPAL, _RESOURCE)
        assert fga.checked
        assert not decision.allowed
        assert decision.reason == "security_revision_changed"

    asyncio.run(run())


def test_batch_precheck_cannot_authorize_across_binding_revision() -> None:
    async def run() -> None:
        journal = FakeJournal()
        decision = (await _plane(journal, FakeFGA(journal)).batch_read(_PRINCIPAL, [_RESOURCE]))[
            _RESOURCE
        ]
        assert not decision.allowed
        assert decision.reason == "security_revision_changed"

    asyncio.run(run())


def test_historical_scope_hint_cannot_grant_access_against_current_binding() -> None:
    class DenyingFGA(FakeFGA):
        async def check(self, _principal: str, _relation: str, _object: str) -> bool:
            self.checked = True
            return False

    class HistoricalKnowledge:
        called = False

        async def get_record(self, *_args: object, **_kwargs: object) -> NodeRecord:
            self.called = True
            return NodeRecord(
                id=_RESOURCE,
                types=["urn:c1:ns:core#Entity"],
                properties={
                    "urn:c1:ns:core#provisionedScopeHint": ["urn:c1:scope:shared"],
                    "http://www.w3.org/2004/02/skos/core#prefLabel": [
                        LiteralValue(
                            lexical="Old visible label",
                            datatype="http://www.w3.org/2001/XMLSchema#string",
                        )
                    ],
                },
            )

    async def run() -> None:
        journal = FakeJournal()
        fga = DenyingFGA(journal)
        knowledge = HistoricalKnowledge()
        runtime = Runtime.__new__(Runtime)
        runtime.journal = cast(Journal, journal)
        runtime.plane = _plane(journal, fga)
        runtime.knowledge = cast(Terminus, knowledge)
        runtime.registry = cast(Any, object())
        result = await runtime.read(_PRINCIPAL, _RESOURCE, revision="branch:old-knowledge")
        assert result is None
        assert fga.checked
        assert not knowledge.called

    asyncio.run(run())


def _try_writer(path: str, result: Any) -> None:
    async def run() -> None:
        gate = WriterGate(Path(path))
        try:
            async with gate.hold():
                result.put("acquired")
        except SecurityError as exc:
            result.put(f"denied:{exc.status}:{exc.reason}")
        finally:
            gate.close()

    asyncio.run(run())


def test_writer_gate_excludes_second_process(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "writer.lock"
        gate = WriterGate(path)
        context = multiprocessing.get_context("spawn")
        result = context.Queue()
        try:
            async with gate.hold():
                child = context.Process(target=_try_writer, args=(str(path), result))
                child.start()
                child.join(timeout=10)
                assert child.exitcode == 0
                assert result.get(timeout=1) == "denied:503:writer_unavailable"
        finally:
            gate.close()

    asyncio.run(run())
