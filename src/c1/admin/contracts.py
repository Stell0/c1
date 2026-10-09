"""Version 1 input/output schemas for public application operator operations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InitializeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    namespace_id: str = Field(min_length=1, max_length=255)


class EnrollmentApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=16384)
    operator: str = Field(min_length=1, max_length=255)
    expires_in: int = Field(ge=60, le=86400)


class NamespaceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_version: Literal[1]
    issuer: str
    namespace_id: str
    instance_id: str
    client_id: str
    subject: str
    operator: str = Field(min_length=1, max_length=255)
    continuity_verified: Literal[True]
    verified_at: float
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class OperatorResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    contract_version: Literal[1]
    error: str | None = None


Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ExternalBackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_version: Literal[1]
    manifest_version: Literal[2]
    type: Literal["external-full"]
    created_at: str = Field(min_length=20, max_length=40)
    operator: str = Field(min_length=1, max_length=255)
    identity: dict[str, Any]
    namespace_id: str = Field(min_length=1, max_length=255)
    fga_store: str = Field(min_length=1)
    fga_model: str = Field(min_length=1)
    model_sha256: Digest
    knowledge_head: str = Field(min_length=1)
    workflow_head: str = Field(min_length=1)
    profiles: dict[str, str]
    security_sha256: Digest
    files: dict[str, Digest]


def schemas() -> dict[str, Any]:
    return {
        "initialize": InitializeInput.model_json_schema(),
        "enrollment_approval": EnrollmentApprovalInput.model_json_schema(),
        "namespace_evidence": NamespaceEvidence.model_json_schema(),
        "operator_result": OperatorResult.model_json_schema(),
        "external_backup_manifest": ExternalBackupManifest.model_json_schema(),
    }
