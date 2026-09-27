"""Operational security state, separate from historical knowledge records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SecurityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(SecurityRecord):
    id: str
    label: str
    state: Literal["provisioning", "active", "retired"] = "active"


class Binding(SecurityRecord):
    resource_id: str
    scope_id: str
    state: Literal["provisioning", "active", "transitioning", "revoked", "failed"]
    inherited_from: str | None = None
    operation_id: str


class Operation(SecurityRecord):
    id: str
    kind: Literal[
        "scope_create",
        "scope_retire",
        "membership",
        "instance_grant",
        "provision",
        "rescope",
        "recover",
        "probe_revision",
    ]
    actor: str
    target: str
    from_scope: str | None = None
    to_scope: str | None = None
    state: Literal["proposed", "approved", "pending", "applied", "failed", "abandoned"]
    approvals: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created: str
    updated: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
