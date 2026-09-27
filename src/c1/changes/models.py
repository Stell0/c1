"""Strict operation payloads and pure ChangeSet lifecycle transitions."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from c1.changes.digest import request_digest


class TransitionError(ValueError):
    """The requested action is not valid in the present lifecycle state."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateOperation(_StrictModel):
    kind: Literal["create"] = "create"
    record: dict[str, Any]
    scope_id: str = Field(min_length=1)
    inherited_from: str | None = None


class ReplaceOperation(_StrictModel):
    kind: Literal["replace"] = "replace"
    resource_id: str = Field(min_length=1)
    record: dict[str, Any]
    reason: str = Field(min_length=1)


class InstallProfileOperation(_StrictModel):
    kind: Literal["install_profile"] = "install_profile"
    profile: str = Field(min_length=1)


class AssertionAssignment(_StrictModel):
    assertion_id: str = Field(min_length=1)
    action: Literal["move", "keep", "retract"]


class ResolveOperation(_StrictModel):
    kind: Literal["resolve"] = "resolve"
    candidates: list[str] = Field(min_length=1)
    decision: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)


class MergeOperation(_StrictModel):
    kind: Literal["merge"] = "merge"
    surviving_id: str = Field(min_length=1)
    merged_id: str = Field(min_length=1)
    alias_plan: Literal["copy", "drop"]
    assertion_plan: list[AssertionAssignment]
    rationale: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)


class SplitOperation(_StrictModel):
    kind: Literal["split"] = "split"
    source_id: str = Field(min_length=1)
    new_entity: dict[str, Any]
    assertion_plan: list[AssertionAssignment]
    rationale: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)


class UndoMergeOperation(_StrictModel):
    kind: Literal["undo_merge"] = "undo_merge"
    resolution_id: str = Field(min_length=1)
    reassignment_plan: list[AssertionAssignment]
    rationale: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)


ChangeOperation = Annotated[
    CreateOperation
    | ReplaceOperation
    | InstallProfileOperation
    | ResolveOperation
    | MergeOperation
    | SplitOperation
    | UndoMergeOperation,
    Field(discriminator="kind"),
]
ChangeSetState = Literal[
    "draft",
    "submitted",
    "validated",
    "approved",
    "applying",
    "applied",
    "rejected",
    "stale",
    "failed",
    "withdrawn",
]


class ChangeSet(_StrictModel):
    """Journal payload; transition methods return a new immutable snapshot.

    Authorization and durable journal CAS are caller responsibilities. The
    state machine only guards lifecycle order and exact-payload links.
    """

    id: str = Field(min_length=1)
    author: str = Field(min_length=1)
    base_revision: str = Field(min_length=1)
    operations: list[ChangeOperation] = Field(min_length=1, max_length=200)
    rationale: str | None = None
    restores_from_revision: str | None = None
    state: ChangeSetState = "draft"
    attempt: int = Field(default=1, ge=1)
    request_digest: str = ""
    approved_digest: str | None = None
    validation_report_id: str | None = None
    review_decision_id: str | None = None
    apply_receipt_id: str | None = None
    reason: str | None = None
    created: str
    updated: str

    @model_validator(mode="after")
    def _check_payload(self) -> Self:
        kinds = {operation.kind for operation in self.operations}
        if "install_profile" in kinds and len(kinds) != 1:
            raise ValueError("install_profile cannot be mixed with content operations")
        digest = request_digest(self.base_revision, self.operations, self.rationale)
        if self.request_digest and self.request_digest != digest:
            raise ValueError("request_digest does not match the proposal payload")
        if not self.request_digest:
            object.__setattr__(self, "request_digest", digest)
        if self.state in {"approved", "applying", "applied"} and self.approved_digest != digest:
            raise ValueError("approved state requires a digest of the exact payload")
        return self

    def _updated(self, *, update: dict[str, Any]) -> ChangeSet:
        """Revalidate transitions, including operation and digest guards."""
        return ChangeSet.model_validate({**self.model_dump(mode="json"), **update})

    def transition(
        self,
        action: Literal[
            "submit",
            "validate",
            "approve",
            "reject",
            "begin_apply",
            "applied",
            "stale",
            "fail",
            "withdraw",
            "edit",
            "rebase",
        ],
        *,
        updated: str,
        operations: list[ChangeOperation] | None = None,
        base_revision: str | None = None,
        rationale: str | None = None,
        validation_report_id: str | None = None,
        review_decision_id: str | None = None,
        apply_receipt_id: str | None = None,
        reason: str | None = None,
    ) -> ChangeSet:
        """Apply a D1 lifecycle action without granting permissions or writing data."""
        state = self.state
        if action == "submit" and state == "draft":
            return self._updated(update={"state": "submitted", "updated": updated})
        if action == "validate" and state == "submitted" and validation_report_id:
            return self._updated(
                update={
                    "state": "validated",
                    "validation_report_id": validation_report_id,
                    "updated": updated,
                }
            )
        if action == "approve" and state == "validated" and review_decision_id:
            return self._updated(
                update={
                    "state": "approved",
                    "approved_digest": self.request_digest,
                    "review_decision_id": review_decision_id,
                    "updated": updated,
                }
            )
        if action == "reject" and state in {"submitted", "validated"} and reason:
            return self._updated(update={"state": "rejected", "reason": reason, "updated": updated})
        if action == "begin_apply" and state == "approved":
            return self._updated(update={"state": "applying", "updated": updated})
        if action == "applied" and state == "applying" and apply_receipt_id:
            return self._updated(
                update={
                    "state": "applied",
                    "apply_receipt_id": apply_receipt_id,
                    "updated": updated,
                }
            )
        if action == "stale" and state in {"approved", "applying"}:
            return self._updated(
                update={"state": "stale", "reason": "base_revision", "updated": updated}
            )
        if action == "fail" and state in {"approved", "applying"} and reason:
            return self._updated(update={"state": "failed", "reason": reason, "updated": updated})
        if action == "withdraw" and state in {
            "draft",
            "submitted",
            "validated",
            "approved",
            "rejected",
            "stale",
            "failed",
        }:
            return self._updated(update={"state": "withdrawn", "updated": updated})
        if (
            action == "edit"
            and state not in {"applying", "applied", "withdrawn"}
            and operations is not None
        ):
            new_rationale = self.rationale if rationale is None else rationale
            return self._updated(
                update={
                    "state": "draft",
                    "attempt": self.attempt + 1,
                    "operations": operations,
                    "rationale": new_rationale,
                    "request_digest": request_digest(self.base_revision, operations, new_rationale),
                    "approved_digest": None,
                    "validation_report_id": None,
                    "review_decision_id": None,
                    "apply_receipt_id": None,
                    "reason": None,
                    "updated": updated,
                }
            )
        if (
            action == "rebase"
            and state in {"submitted", "validated", "approved", "rejected", "stale", "failed"}
            and base_revision
        ):
            return self._updated(
                update={
                    "state": "submitted",
                    "attempt": self.attempt + 1,
                    "base_revision": base_revision,
                    "request_digest": request_digest(
                        base_revision, self.operations, self.rationale
                    ),
                    "approved_digest": None,
                    "validation_report_id": None,
                    "review_decision_id": None,
                    "apply_receipt_id": None,
                    "reason": None,
                    "updated": updated,
                }
            )
        raise TransitionError(f"cannot {action} a ChangeSet in state {state}")
