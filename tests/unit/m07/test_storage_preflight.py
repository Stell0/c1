"""Known pre-write mapping failures cannot leave publication permanently pending.

These tests use the real mapper and receipt search with a synthetic journal;
they verify recovery decisions, not live backend atomicity guarantees.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from c1.api.routes.changesets import ChangeSetCreate, OperationsEdit
from c1.authorization.errors import SecurityError
from c1.authorization.journal import _decode, _encode
from c1.authorization.models import Binding, Operation
from c1.authorization.operations import WriterGate
from c1.authorization.principal import Principal
from c1.changes.apply import ChangeService
from c1.changes.digest import receipt_message, request_digest
from c1.changes.idempotency import idempotency_address, idempotency_entry
from c1.changes.models import ChangeSet, CreateOperation, InstallProfileOperation
from c1.changes.storage import storage_diagnostics
from c1.model.literals import LiteralValue
from c1.model.profiles import ProfileRegistry
from c1.model.records import EntityRecord
from c1.storage.terminus import StorageError

BASE = "urn:c1:instance:test:"
AUTHOR = "user:local.author"
REVIEWER = "user:local.reviewer"
INVALID_ID = BASE + "entity/" + str(uuid5(NAMESPACE_URL, "synthetic-invalid-canonical-id"))
VALID_ID = BASE + "entity/00000000-0000-4000-8000-000000000001"
NOW = "2026-09-28T00:00:00Z"
Entry = tuple[str, str, dict[str, Any]]


class MemoryJournal:
    def __init__(self, entries: Sequence[Entry]) -> None:
        self.entries = {(kind, key): copy.deepcopy(value) for kind, key, value in entries}
        self.batches: list[list[Entry]] = []

    async def head(self) -> str:
        return "workflow-head"

    async def get(self, kind: str, key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.entries.get((kind, key)))

    async def list(self, kind: str) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(value)
            for (actual_kind, _), value in self.entries.items()
            if actual_kind == kind
        ]

    async def save_many(self, entries: Sequence[Entry], expected_head: str | None = None) -> str:
        assert expected_head in {None, "workflow-head"}
        batch = copy.deepcopy(list(entries))
        self.batches.append(batch)
        self.entries.update({(kind, key): value for kind, key, value in batch})
        return "workflow-after"


def _record(identifier: str = INVALID_ID) -> EntityRecord:
    return EntityRecord(
        id=identifier,
        labels=[
            LiteralValue(
                lexical="Synthetic entity", datatype="http://www.w3.org/2001/XMLSchema#string"
            )
        ],
    )


def _pending() -> tuple[ChangeSet, Operation, MemoryJournal]:
    changeset = ChangeSet(
        id="synthetic-cs",
        author=AUTHOR,
        base_revision="branch:base",
        operations=[
            CreateOperation(record=_record().to_node().model_dump(mode="json"), scope_id="scope")
        ],
        created=NOW,
        updated=NOW,
    )
    changeset = (
        changeset.transition("submit", updated=NOW)
        .transition("validate", updated=NOW, validation_report_id="validation")
        .transition("approve", updated=NOW, review_decision_id="review")
        .transition("begin_apply", updated=NOW)
    )
    bindings = {
        INVALID_ID: Binding(
            resource_id=INVALID_ID,
            scope_id="scope",
            state="provisioning",
            operation_id="synthetic-op",
        ),
        "urn:synthetic:own-activity": Binding(
            resource_id="urn:synthetic:own-activity",
            scope_id="scope",
            state="provisioning",
            operation_id="synthetic-op",
        ),
        "urn:synthetic:active": Binding(
            resource_id="urn:synthetic:active",
            scope_id="scope",
            state="active",
            operation_id="prior-op",
        ),
        "urn:synthetic:foreign": Binding(
            resource_id="urn:synthetic:foreign",
            scope_id="scope",
            state="provisioning",
            operation_id="other-op",
        ),
    }
    operation = Operation(
        id="synthetic-op",
        kind="changeset_apply",
        actor=REVIEWER,
        target=changeset.id,
        state="pending",
        targets=list(bindings),
        payload={
            "records": [_record().to_node().model_dump(mode="json")],
            "bindings": {key: value.scope_id for key, value in bindings.items()},
            "base_revision": changeset.base_revision,
            "idempotency_key": "apply-key",
        },
        created=NOW,
        updated=NOW,
    )
    entries: list[Entry] = [
        ("ChangeSet", changeset.id, changeset.model_dump(mode="json")),
        ("Operation", operation.id, operation.model_dump(mode="json")),
        ("ReviewDecision", "review", {"actor": REVIEWER}),
        idempotency_entry(
            REVIEWER,
            "knowledge",
            "apply-key",
            str(changeset.approved_digest),
            changeset.id,
            changeset.model_dump(mode="json"),
        ),
    ]
    entries.extend(
        ("Binding", key, binding.model_dump(mode="json")) for key, binding in bindings.items()
    )
    return changeset, operation, MemoryJournal(entries)


def _service(journal: MemoryJournal) -> ChangeService:
    service = object.__new__(ChangeService)
    service.settings = cast(
        Any,
        SimpleNamespace(
            instance_base=BASE,
            knowledge_database="knowledge",
            enable_probe_routes=False,
            crash_after="",
        ),
    )
    service.journal = cast(Any, journal)
    service.registry = ProfileRegistry()
    service.knowledge = cast(Any, AsyncMock())
    cast(Any, service.knowledge).head.return_value = "branch:base"

    async def log(*, start: int, count: int) -> list[dict[str, Any]]:
        assert count == 20
        return (
            [
                {"identifier": f"prior-{index}", "message": "unrelated prior commit"}
                for index in range(20)
            ]
            if start == 0
            else []
        )

    cast(Any, service.knowledge).log.side_effect = log
    service.fga = cast(Any, AsyncMock())
    cast(Any, service.fga).bindings.return_value = []
    service.plane = cast(Any, AsyncMock())

    async def binding(identifier: str) -> Binding | None:
        value = await journal.get("Binding", identifier)
        return Binding.model_validate(value) if value is not None else None

    cast(Any, service.plane).bindings.side_effect = binding
    service.audit = cast(Any, SimpleNamespace(emit=Mock()))
    cast(Any, service)._require_all = AsyncMock(
        side_effect=SecurityError(403, "authorization_denied")
    )
    return service


def _assert_no_external_mutation(service: ChangeService) -> None:
    cast(Any, service.knowledge).upsert_records.assert_not_awaited()
    assert all(call[0] == "bindings" for call in cast(Any, service.fga).mock_calls)
    assert all(call[0] == "bindings" for call in cast(Any, service.plane).mock_calls)


def test_known_mapping_failure_cleans_own_pending_state_before_revoked_permissions() -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        untouched = {
            key: copy.deepcopy(value)
            for key, value in journal.entries.items()
            if key in {("Binding", "urn:synthetic:active"), ("Binding", "urn:synthetic:foreign")}
        }
        service = _service(journal)
        await service._reconcile(operation, changeset)
        assert journal.entries[("ChangeSet", changeset.id)]["state"] == "failed"
        assert journal.entries[("Operation", operation.id)]["state"] == "failed"
        assert all(
            journal.entries[("Binding", identifier)]["state"] == "failed"
            for identifier in (INVALID_ID, "urn:synthetic:own-activity")
        )
        assert all(journal.entries[key] == value for key, value in untouched.items())
        replay = journal.entries[
            ("Idempotency", idempotency_address(REVIEWER, "knowledge", "apply-key"))
        ]
        assert replay["response"]["state"] == "failed"
        assert replay["digest"] == changeset.approved_digest
        assert len(journal.batches) == 1
        assert {kind for kind, _, _ in journal.batches[0]} == {
            "ChangeSet",
            "Operation",
            "Binding",
            "Idempotency",
        }
        cast(Any, service)._require_all.assert_not_awaited()
        assert cast(Any, service.knowledge).log.await_count == 6
        cast(Any, service.knowledge).log.assert_any_await(start=20, count=20)
        _assert_no_external_mutation(service)

    asyncio.run(case())


@pytest.mark.parametrize(
    "uncertain", ["receipt", "changed-head", "changed-head-final", "unknown-head", "incomplete-log"]
)
def test_uncertain_commit_observations_cannot_terminally_abort(uncertain: str) -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        service = _service(journal)
        before = copy.deepcopy(journal.entries)
        knowledge = cast(Any, service.knowledge)
        if uncertain == "receipt":
            message = receipt_message(
                changeset_id=changeset.id,
                attempt=changeset.attempt,
                principal_id=operation.actor,
                repository="knowledge",
                digest=str(changeset.approved_digest),
            )
            knowledge.log.side_effect = [[{"identifier": "committed", "message": message}]]
        elif uncertain == "changed-head":
            knowledge.head.return_value = "branch:later"
        elif uncertain == "changed-head-final":
            knowledge.head.side_effect = ["branch:base", "branch:base", "branch:later"]
        elif uncertain == "unknown-head":
            knowledge.head.side_effect = StorageError("C1-ST-002", "unavailable head")
        else:
            knowledge.log.side_effect = [
                [{"identifier": f"prior-{index}", "message": "prior"} for index in range(20)],
                StorageError("C1-ST-002", "unavailable later log page"),
            ]
        try:
            assert not await service._abort_unrepresentable(operation, changeset)
        except (StorageError, SecurityError):
            # Propagation also leaves uncertainty pending for the coordinator.
            pass
        assert journal.entries == before and journal.batches == []
        assert operation.state == "pending" and "failure_reason" not in operation.payload
        _assert_no_external_mutation(service)

    asyncio.run(case())


@pytest.mark.parametrize("publication_evidence", ["active-own-binding", "fga-tuple"])
def test_existing_publication_evidence_preserves_pending_barrier(publication_evidence: str) -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        service = _service(journal)
        if publication_evidence == "active-own-binding":
            journal.entries[("Binding", INVALID_ID)]["state"] = "active"
        else:
            cast(Any, service.fga).bindings.return_value = ["access_scope:scope"]
        before = copy.deepcopy(journal.entries)
        with pytest.raises(SecurityError, match="recovery_binding_changed"):
            await service._abort_unrepresentable(operation, changeset)
        assert journal.entries == before and journal.batches == []
        assert operation.state == "pending" and "failure_reason" not in operation.payload
        _assert_no_external_mutation(service)

    asyncio.run(case())


def test_failed_apply_replays_same_key_only_after_current_visibility(tmp_path: Path) -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        service = _service(journal)
        service.writer = WriterGate(tmp_path / "storage-preflight.lock")
        try:
            await service._reconcile(operation, changeset)
            writes = len(journal.batches)
            visible = AsyncMock(return_value=True)
            cast(Any, service)._visible = visible
            principal = Principal("local", "reviewer", "human")
            replay = await service.apply(principal, changeset.id, "apply-key")
            assert replay["state"] == "failed" and replay["replayed"] is True
            visible.assert_awaited_once()
            assert len(journal.batches) == writes
            with pytest.raises(SecurityError, match="not_approved"):
                await service.apply(principal, changeset.id, "different-key")
            assert len(journal.batches) == writes
            visible.return_value = False
            with pytest.raises(SecurityError) as error:
                await service.apply(principal, changeset.id, "apply-key")
            assert error.value.status == 404
            assert len(journal.batches) == writes
            _assert_no_external_mutation(service)
        finally:
            service.writer.close()

    asyncio.run(case())


@pytest.mark.parametrize("mismatch", ["target", "base", "approved-digest"])
def test_reconciliation_rejects_mismatched_intent_before_terminal_cleanup(mismatch: str) -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        service = _service(journal)
        if mismatch == "target":
            operation.target = "different-changeset"
        elif mismatch == "base":
            operation.payload["base_revision"] = "branch:different"
        else:
            changeset = changeset.model_copy(update={"approved_digest": "b" * 64})
        before = copy.deepcopy(journal.entries)
        with pytest.raises(SecurityError, match="recovery_payload_mismatch"):
            await service._reconcile(operation, changeset)
        assert journal.entries == before and journal.batches == []
        cast(Any, service.knowledge).log.assert_not_awaited()
        cast(Any, service.knowledge).head.assert_not_awaited()
        _assert_no_external_mutation(service)

    asyncio.run(case())


def test_representable_payload_does_not_repeat_receipt_or_policy_reads() -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        operation.payload["records"] = [_record(VALID_ID).to_node().model_dump(mode="json")]
        service = _service(journal)
        assert not await service._abort_unrepresentable(operation, changeset)
        assert journal.batches == []
        cast(Any, service.knowledge).log.assert_not_awaited()
        cast(Any, service.knowledge).head.assert_not_awaited()
        _assert_no_external_mutation(service)

    asyncio.run(case())


def test_mapper_error_other_than_known_prewrite_diagnostic_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def case() -> None:
        changeset, operation, journal = _pending()
        service = _service(journal)
        before = copy.deepcopy(journal.entries)

        def unavailable(*_args: Any, **_kwargs: Any) -> Any:
            raise StorageError("C1-ST-005", "unexpected mapping error")

        monkeypatch.setattr("c1.changes.apply.records_to_documents", unavailable)
        try:
            assert not await service._abort_unrepresentable(operation, changeset)
        except StorageError:
            pass
        assert journal.entries == before and journal.batches == []
        _assert_no_external_mutation(service)

    asyncio.run(case())


def test_storage_preflight_reports_invalid_canonical_uuid_without_persisting() -> None:
    registry = ProfileRegistry()
    diagnostics = storage_diagnostics(
        [CreateOperation(record=_record().to_node().model_dump(mode="json"), scope_id="scope")],
        registry,
        BASE,
    )
    assert len(diagnostics) == 1 and diagnostics[0].severity == "error"
    assert diagnostics[0].code == "C1-ST-004"
    assert (
        storage_diagnostics(
            [
                CreateOperation(
                    record=_record(VALID_ID).to_node().model_dump(mode="json"), scope_id="scope"
                )
            ],
            registry,
            BASE,
        )
        == []
    )


def test_legacy_applied_multi_profile_journal_can_decode_but_requests_still_reject() -> None:
    operations = [
        InstallProfileOperation(profile="first"),
        InstallProfileOperation(profile="second"),
    ]
    digest = request_digest("branch:base", operations, None)
    legacy = {
        "id": "legacy-applied",
        "author": AUTHOR,
        "base_revision": "branch:base",
        "operations": [operation.model_dump(mode="json") for operation in operations],
        "state": "applied",
        "request_digest": digest,
        "approved_digest": digest,
        "apply_receipt_id": "legacy-receipt",
        "created": NOW,
        "updated": NOW,
    }
    decoded = _decode(_encode("ChangeSet", "legacy-applied", legacy))[2]
    assert ChangeSet.model_validate(decoded).state == "applied"
    with pytest.raises(ValidationError, match="exactly one"):
        ChangeSetCreate.model_validate(
            {"base_revision": "branch:base", "operations": legacy["operations"]}
        )
    with pytest.raises(ValidationError, match="exactly one"):
        OperationsEdit.model_validate({"operations": legacy["operations"]})
    mixed = [
        operations[0],
        CreateOperation(
            record=_record(VALID_ID).to_node().model_dump(mode="json"), scope_id="scope"
        ),
    ]
    mixed_digest = request_digest("branch:base", mixed, None)
    with pytest.raises(ValidationError, match="cannot be mixed"):
        ChangeSet.model_validate(
            {
                **legacy,
                "operations": [item.model_dump(mode="json") for item in mixed],
                "request_digest": mixed_digest,
                "approved_digest": mixed_digest,
            }
        )
