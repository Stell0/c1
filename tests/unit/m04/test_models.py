"""ChangeSet payload typing, workflow, and review invalidation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from c1.authorization.journal import _decode, _encode
from c1.changes.models import ChangeSet, CreateOperation, InstallProfileOperation, TransitionError


def _draft() -> ChangeSet:
    return ChangeSet(
        id="cs-1",
        author="issuer|bob",
        base_revision="H",
        operations=[CreateOperation(record={"id": "urn:c1:1"}, scope_id="S")],
        created="2026-09-27T00:00:00Z",
        updated="2026-09-27T00:00:00Z",
    )


def test_typed_payload_and_journal_roundtrip() -> None:
    draft = _draft()
    assert draft.request_digest
    envelope = _encode("ChangeSet", draft.id, draft.model_dump(mode="json"))
    assert ChangeSet.model_validate(_decode(envelope)[2]) == draft
    with pytest.raises(ValidationError):
        ChangeSet.model_validate({**draft.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        ChangeSet.model_validate(
            {**draft.model_dump(), "operations": [{"kind": "delete", "resource_id": "x"}]}
        )


@pytest.mark.parametrize(
    "kind",
    [
        "ChangeSet",
        "ValidationReport",
        "ReviewDecision",
        "ApplyReceipt",
        "Idempotency",
        "MigrationProposal",
    ],
)
def test_m04_journal_kinds_roundtrip(kind: str) -> None:
    assert _decode(_encode(kind, "same-key", {"kind": kind})) == (
        kind,
        "same-key",
        {"kind": kind},
    )


def test_content_and_schema_operations_cannot_mix() -> None:
    with pytest.raises(ValidationError, match="cannot be mixed"):
        ChangeSet.model_validate(
            {
                "id": "cs-1",
                "author": "p",
                "base_revision": "H",
                "operations": [
                    {"kind": "create", "record": {}, "scope_id": "S"},
                    {"kind": "install_profile", "profile": "core"},
                ],
                "created": "t",
                "updated": "t",
            }
        )


def test_edit_revalidates_operation_partition() -> None:
    with pytest.raises(ValidationError, match="cannot be mixed"):
        _draft().transition(
            "edit",
            updated="t2",
            operations=[
                CreateOperation(record={}, scope_id="S"),
                InstallProfileOperation(profile="core"),
            ],
        )


def test_approved_payload_edit_invalidates_and_increments_attempt() -> None:
    draft = _draft()
    submitted = draft.transition("submit", updated="t1")
    validated = submitted.transition("validate", updated="t2", validation_report_id="v1")
    approved = validated.transition("approve", updated="t3", review_decision_id="r1")
    assert approved.approved_digest == approved.request_digest
    with pytest.raises(TransitionError):
        draft.transition("begin_apply", updated="t4")
    edited = approved.transition(
        "edit",
        updated="t4",
        operations=[CreateOperation(record={"id": "urn:c1:2"}, scope_id="S")],
    )
    assert edited.state == "draft"
    assert edited.attempt == 2
    assert edited.request_digest != approved.request_digest
    assert edited.validation_report_id is None
    assert edited.review_decision_id is None
    assert edited.approved_digest is None
    with pytest.raises(TransitionError):
        edited.transition("begin_apply", updated="t5")


def test_stale_rebase_requires_new_validation_and_approval() -> None:
    approved = (
        _draft()
        .transition("submit", updated="t1")
        .transition("validate", updated="t2", validation_report_id="v1")
        .transition("approve", updated="t3", review_decision_id="r1")
    )
    stale = approved.transition("stale", updated="t4")
    rebased = stale.transition("rebase", updated="t5", base_revision="H2")
    assert rebased.state == "submitted"
    assert rebased.attempt == 2
    assert rebased.base_revision == "H2"
    assert rebased.approved_digest is None
    with pytest.raises(TransitionError):
        rebased.transition("approve", updated="t6", review_decision_id="r2")


def test_apply_and_terminal_guards() -> None:
    approved = (
        _draft()
        .transition("submit", updated="t1")
        .transition("validate", updated="t2", validation_report_id="v1")
        .transition("approve", updated="t3", review_decision_id="r1")
    )
    applied = approved.transition("begin_apply", updated="t4").transition(
        "applied", updated="t5", apply_receipt_id="receipt-1"
    )
    assert applied.state == "applied"
    with pytest.raises(TransitionError):
        applied.transition("edit", updated="t6", operations=approved.operations)
