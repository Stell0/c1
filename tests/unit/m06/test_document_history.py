"""Document history uses authorized manifests and backend revisions safely."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.principal import Principal
from c1.documents.service import DocumentsService, _history_candidates
from c1.model.nodes import NodeRecord
from c1.model.records import C1
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords
from c1.runtime import Runtime
from c1.storage.terminus import StorageError

DOC = "urn:c1:test:document"
OTHER = "urn:c1:test:other-document"
P = "urn:c1:test:moved-part"
Q = "urn:c1:test:current-part"
UNRELATED = "urn:c1:test:unrelated"
HEAD = "branch:r4"
PRINCIPAL = Principal("test", "alice", "human")


def _node(identifier: str, kind: str, parent: str | None = None) -> NodeRecord:
    return NodeRecord(
        id=identifier,
        types=[C1 + kind],
        properties={C1 + "partOfDocument": [parent]} if parent else {},
    )


def _records(*nodes: NodeRecord) -> AuthorizedRecords:
    return AuthorizedRecords({node.id: node for node in nodes}, {})


def _operation(kind: str, *nodes: NodeRecord, target: str = "cs") -> dict[str, Any]:
    payload = (
        {"records": [node.model_dump(mode="json") for node in nodes]}
        if kind == "changeset_apply"
        else {"record": nodes[0].model_dump(mode="json")}
    )
    return {"kind": kind, "state": "applied", "target": target, "payload": payload}


def test_history_candidates_use_applied_payloads_and_complete_creation_origins() -> None:
    expanded = "urn:c1:test:expanded-part"
    legacy = "urn:c1:test:legacy-part"
    provisioned = "urn:c1:test:provisioned-part"
    hidden = "urn:c1:test:hidden-part"
    records = _records(
        _node(DOC, "Document"),
        _node(P, "DocumentPart", OTHER),
        _node(expanded, "Source"),
        _node(legacy, "DocumentPart", DOC),
        _node(provisioned, "DocumentPart", DOC),
    )
    plan = AuthorizedPlan("security-head", frozenset(), tuple(records), {})
    applied = _operation(
        "changeset_apply", _node(P, "DocumentPart", DOC), _node(expanded, "DocumentPart", DOC)
    )
    # An inaccessible malformed manifest cannot even enter parsing or hints.
    applied["payload"]["records"].append({"id": hidden, "types": []})
    journal = {
        "ChangeSet": [
            {
                "id": "cs",
                "state": "applied",
                "operations": [
                    {"kind": "create", "record": {"id": P, "types": ["urn:ignored:draft"]}},
                    {"kind": "create", "record": {"id": expanded}},
                ],
            }
        ],
        "Operation": [
            applied,
            _operation("changeset_apply", _node(P, "Source"), target="later"),
            _operation("provision", _node(provisioned, "DocumentPart", DOC), target=provisioned),
            _operation("probe_revision", _node(provisioned, "Source"), target=provisioned),
            {**_operation("changeset_apply", _node(legacy, "Source")), "state": "pending"},
        ],
    }
    candidates, types = _history_candidates(DOC, plan, records, journal)
    assert candidates == {P, expanded, legacy, provisioned}
    assert types == {
        P: frozenset({C1 + "DocumentPart", C1 + "Source"}),
        expanded: frozenset({C1 + "DocumentPart", C1 + "Source"}),
        provisioned: frozenset({C1 + "DocumentPart", C1 + "Source"}),
    }
    assert legacy not in types and hidden not in types


def _entry(index: int) -> dict[str, Any]:
    return {
        "revision": f"branch:r{index}",
        "recorded_at": f"2026-09-28T00:00:0{index}Z",
        "changeset_id": None,
        "attempt": None,
    }


def _service(monkeypatch: pytest.MonkeyPatch) -> tuple[DocumentsService, Any, AuthorizedPlan]:
    document = _node(DOC, "Document")
    records = _records(
        document,
        _node(P, "DocumentPart", OTHER),
        _node(Q, "DocumentPart", DOC),
        _node(UNRELATED, "Source"),
    )
    plan = AuthorizedPlan("security-head", frozenset(), tuple(records), {})
    journal = {
        "ChangeSet": [
            {
                "id": "cs",
                "state": "applied",
                "operations": [{"kind": "create", "record": {"id": key}} for key in (DOC, P)],
            }
        ],
        "Operation": [
            _operation(
                "changeset_apply",
                document,
                _node(P, "DocumentPart", DOC),
                _node(Q, "DocumentPart", DOC),
            )
        ],
    }
    snapshots = {
        "branch:r1": _records(
            document, _node(P, "DocumentPart", DOC), _node(Q, "DocumentPart", DOC)
        ),
        "branch:r2": _records(
            document, _node(P, "DocumentPart", OTHER), _node(Q, "DocumentPart", DOC)
        ),
        "branch:r3": records,
    }
    histories = {
        DOC: [_entry(0)],
        P: [_entry(index) for index in (4, 3, 2, 1)],
        Q: [_entry(2), _entry(1)],
    }

    async def metadata(_plan: AuthorizedPlan, key: str, _revision: str, **_kwargs: Any) -> Any:
        return {"items": histories[key], "next_cursor": None}

    async def snapshot(_plan: AuthorizedPlan, revision: str, **_kwargs: Any) -> Any:
        return snapshots[revision]

    runtime = SimpleNamespace(
        settings=SimpleNamespace(instance_id="history-test", query_time_budget_ms=2000),
        knowledge=SimpleNamespace(head=AsyncMock(return_value=HEAD)),
        journal=SimpleNamespace(
            head=AsyncMock(return_value="security-head"),
            list_many=AsyncMock(return_value=journal),
        ),
        changes=SimpleNamespace(
            history_service=SimpleNamespace(metadata=AsyncMock(side_effect=metadata))
        ),
        query=SimpleNamespace(
            records=AsyncMock(side_effect=snapshot),
            planner=SimpleNamespace(finalize=AsyncMock()),
        ),
    )
    service = DocumentsService(cast(Runtime, runtime))
    monkeypatch.setattr(
        service,
        "_selection",
        AsyncMock(return_value=(plan, records, HEAD, time.monotonic() + 5)),
    )
    return service, runtime, plan


def test_document_history_includes_departure_and_reuses_revision_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, plan = _service(monkeypatch)
        result = await service.history(PRINCIPAL, DOC)
        assert [item["revision"] for item in result["items"]] == [
            "branch:r2",
            "branch:r1",
            "branch:r0",
        ]
        assert result["count"] == 3
        revisions = [call.args[1] for call in runtime.query.records.await_args_list]
        assert sorted(revisions) == ["branch:r1", "branch:r2", "branch:r3"]
        assert all(call.args[0] is plan for call in runtime.query.records.await_args_list)
        calls = runtime.changes.history_service.metadata.await_args_list
        assert {call.args[1] for call in calls} == {DOC, P, Q}
        assert all(call.args[0] is plan and call.args[2] == HEAD for call in calls)
        hints = {call.args[1]: call.kwargs["storage_types"] for call in calls}
        assert hints[P] == frozenset({C1 + "DocumentPart"})
        assert hints[Q] is None  # Untracked creation must retain full-class probes.
        gates = {id(call.kwargs["backend_gate"]) for call in calls}
        assert len(gates) == 1
        runtime.query.planner.finalize.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("historical_kind", [None, "Assertion"])
def test_snapshot_narrowing_requires_complete_reference_independent_types(
    monkeypatch: pytest.MonkeyPatch, historical_kind: str | None
) -> None:
    async def run() -> None:
        service, runtime, plan = _service(monkeypatch)
        journal = runtime.journal.list_many.return_value
        journal["ChangeSet"][0]["operations"].append({"kind": "create", "record": {"id": Q}})
        if historical_kind is not None:
            journal["Operation"].append(
                _operation("changeset_apply", _node(P, historical_kind), target="later")
            )
        result = await service.history(PRINCIPAL, DOC)
        assert result["count"] == 3
        for call in runtime.query.records.await_args_list:
            snapshot_plan = call.args[0]
            if historical_kind is None:
                assert snapshot_plan is not plan
                assert set(snapshot_plan.authorized_ids) == {DOC, P, Q}
                assert not snapshot_plan.contains(UNRELATED)
            else:
                assert snapshot_plan is plan
                assert snapshot_plan.contains(UNRELATED)
        assert runtime.query.planner.finalize.await_args.args[1] is plan

    asyncio.run(run())


@pytest.mark.parametrize(
    "manifest_heads", [("security-head", "changed-head"), ("older-head", "older-head")]
)
def test_manifest_races_reject_before_candidates_or_history_fetches(
    monkeypatch: pytest.MonkeyPatch, manifest_heads: tuple[str, str]
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        runtime.journal.head.side_effect = manifest_heads

        def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("A stale manifest cannot supply candidates or class hints")

        monkeypatch.setattr("c1.documents.service._history_candidates", forbidden)
        with pytest.raises(QueryPlanError) as caught:
            await service.history(PRINCIPAL, DOC)
        assert caught.value.status == 409 and caught.value.code == "C1-DC-014"
        assert runtime.journal.head.await_count == 2
        runtime.changes.history_service.metadata.assert_not_awaited()
        runtime.query.records.assert_not_awaited()
        runtime.query.planner.finalize.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["read_revoked", "binding_changed", "security_head_changed"])
def test_final_authorization_failure_prevents_document_history_publication(
    monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        failure = QueryPlanError(403, "C1-QY-003", reason)
        order: list[str] = []

        async def head() -> str:
            order.append("head")
            return HEAD

        async def finalize(*_args: Any, **_kwargs: Any) -> None:
            order.append("finalize")
            raise failure

        runtime.knowledge.head.side_effect = head
        runtime.query.planner.finalize.side_effect = finalize
        with pytest.raises(QueryPlanError) as caught:
            await service.history(PRINCIPAL, DOC)
        assert caught.value is failure
        assert order == ["head", "finalize"]
        runtime.query.planner.finalize.assert_awaited_once()

    asyncio.run(run())


def test_changed_knowledge_head_prevents_document_history_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        runtime.knowledge.head.return_value = "branch:changed"
        with pytest.raises(QueryPlanError) as caught:
            await service.history(PRINCIPAL, DOC)
        assert caught.value.reason == "restart_required"
        runtime.query.planner.finalize.assert_not_awaited()

    asyncio.run(run())


def test_document_history_checks_head_before_final_authorization_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        order: list[str] = []

        async def head() -> str:
            order.append("head")
            return HEAD

        async def finalize(*_args: Any, **_kwargs: Any) -> None:
            order.append("finalize")

        runtime.knowledge.head.side_effect = head
        runtime.query.planner.finalize.side_effect = finalize
        response = await service.history(PRINCIPAL, DOC)
        assert response["count"] == 3
        assert order == ["head", "finalize"]

    asyncio.run(run())


def test_failed_metadata_cancels_and_awaits_document_history_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        service, runtime, _plan = _service(monkeypatch)
        failure = StorageError("C1-ST-003", "backend failed")
        cancelled: set[str] = set()
        active: set[str] = set()

        async def metadata(_plan: AuthorizedPlan, key: str, _revision: str, **_kwargs: Any) -> Any:
            active.add(key)
            try:
                if key == DOC:
                    await asyncio.sleep(0)
                    raise failure
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(key)
                raise
            finally:
                active.remove(key)

        runtime.changes.history_service.metadata.side_effect = metadata
        with pytest.raises(StorageError) as caught:
            await service.history(PRINCIPAL, DOC)
        assert caught.value is failure
        assert cancelled == {P, Q} and not active
        runtime.query.records.assert_not_awaited()
        runtime.query.planner.finalize.assert_not_awaited()

    asyncio.run(run())
