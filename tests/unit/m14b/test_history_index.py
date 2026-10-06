"""M14b D7 (ADR-0026): history from the journal and the knowledge commit log."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.changes.history import HistoryService
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import Terminus

R = "urn:c1:instance:dev:entity/00000001-0000-4000-8000-000000000000"


def _op(kind: str, target: str, revision: str, ids: list[str], state: str = "applied") -> Any:
    payload: dict[str, Any] = {"revision": revision}
    if kind == "changeset_apply":
        payload["records"] = [{"id": i} for i in ids]
    else:
        payload["record"] = {"id": ids[0]}
    return {"kind": kind, "target": target, "state": state, "payload": payload}


class FakeJournal:
    def __init__(self, operations: list[Any]) -> None:
        self.operations = operations

    async def list(self, kind: str) -> list[Any]:
        return self.operations if kind == "Operation" else []


class FakeKnowledge:
    def __init__(self, log: list[dict[str, Any]]) -> None:
        self.entries = log

    async def log(self, *, start: int | None = None, count: int | None = None) -> list[Any]:
        begin = start or 0
        return self.entries[begin : begin + (count or 100)]


def _commit(identifier: str, changeset: str) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "author": "c1-model",
        "timestamp": 1.0,
        "message": json.dumps({"c1": 2, "changeset": changeset, "attempt": 1}),
    }


def _service(operations: list[Any], log: list[dict[str, Any]]) -> HistoryService:
    return HistoryService(
        cast(Terminus, FakeKnowledge(log)),
        cast(AuthorizationPlane, None),
        cast(Journal, FakeJournal(operations)),
        ProfileRegistry(),
    )


def test_indexed_history_is_newest_first_and_skips_unreachable_commits() -> None:
    operations = [
        _op("changeset_apply", "cs-1", "branch:c1", [R]),
        _op("changeset_apply", "cs-2", "branch:c2", [R, "urn:other"]),
        _op("changeset_apply", "cs-3", "branch:c3", ["urn:other"]),
        _op("changeset_apply", "cs-gone", "branch:cgone", [R]),  # restored away
        _op("changeset_apply", "cs-4", "branch:c4", [R], state="pending"),
    ]
    log = [_commit("c3", "cs-3"), _commit("c2", "cs-2"), _commit("c1", "cs-1")]
    found = asyncio.run(_service(operations, log)._indexed_history(R))
    assert [entry["identifier"] for entry in found or []] == ["c2", "c1"]


def test_provisioned_or_untracked_resources_use_backend_probes() -> None:
    provisioned = [
        _op("changeset_apply", "cs-1", "branch:c1", [R]),
        _op("provision", "op", "branch:c9", [R]),
    ]
    log = [_commit("c1", "cs-1")]
    assert asyncio.run(_service(provisioned, log)._indexed_history(R)) is None
    assert asyncio.run(_service([], log)._indexed_history(R)) is None


def test_receipt_mismatch_falls_back() -> None:
    operations = [_op("changeset_apply", "cs-1", "branch:c1", [R])]
    log = [_commit("c1", "someone-else")]
    assert asyncio.run(_service(operations, log)._indexed_history(R)) is None
