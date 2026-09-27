"""Authenticated ChangeSet workflow endpoints; business rules live in the service."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.errors import SecurityError
from c1.authorization.principal import Principal
from c1.changes.models import ChangeOperation
from c1.runtime import Runtime

router = APIRouter(prefix="/v1/changesets")


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChangeSetCreate(_StrictRequest):
    base_revision: str = Field(min_length=1)
    operations: list[ChangeOperation] = Field(min_length=1, max_length=200)
    rationale: str | None = None
    restores_from_revision: str | None = None


class OperationsEdit(_StrictRequest):
    operations: list[ChangeOperation] = Field(min_length=1, max_length=200)


class RejectRequest(_StrictRequest):
    reason: str = Field(min_length=1)


class RebaseRequest(_StrictRequest):
    base_revision: str = Field(min_length=1)


class EmptyRequest(_StrictRequest):
    pass


def _idempotency_key(request: Request) -> str:
    values = request.headers.getlist("idempotency-key")
    if len(values) != 1 or not 1 <= len(values[0]) <= 128:
        raise SecurityError(400, "invalid_idempotency_key")
    key = values[0]
    if any(not 0x20 <= ord(char) <= 0x7E for char in key):
        raise SecurityError(400, "invalid_idempotency_key")
    return key


@router.post("", status_code=201, name="changeset_create", response_model=None)
async def create(
    body: ChangeSetCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any] | JSONResponse:
    result = await runtime.changes.create(principal, body, _idempotency_key(request))
    audit(request, principal, "changeset_create", target=str(result.get("id", "")))
    if result.get("replayed") is True:
        return JSONResponse(status_code=200, content=result)
    return result


@router.get("", name="changeset_list")
async def list_changesets(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.list(principal)
    audit(request, principal, "changeset_list")
    return result


@router.get("/{changeset_id}/validation", name="changeset_validation_read")
async def get_validation(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.get_validation(principal, changeset_id)
    audit(request, principal, "changeset_validation_read", target=changeset_id)
    return result


@router.get("/{changeset_id}", name="changeset_read")
async def get_changeset(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.get(principal, changeset_id)
    audit(request, principal, "changeset_read", target=changeset_id)
    return result


@router.put("/{changeset_id}/operations", name="changeset_edit")
async def edit(
    changeset_id: str,
    body: OperationsEdit,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.edit(principal, changeset_id, body.operations)
    audit(request, principal, "changeset_edit", target=changeset_id)
    return result


@router.post("/{changeset_id}/submit", name="changeset_submit")
async def submit(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: EmptyRequest | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.submit(principal, changeset_id)
    audit(request, principal, "changeset_submit", target=changeset_id)
    return result


@router.post("/{changeset_id}/validate", name="changeset_validate")
async def validate(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: EmptyRequest | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.validate(principal, changeset_id)
    audit(request, principal, "changeset_validate", target=changeset_id)
    return result


@router.post("/{changeset_id}/approve", name="changeset_approve")
async def approve(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: EmptyRequest | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.approve(principal, changeset_id)
    audit(request, principal, "changeset_approve", target=changeset_id)
    return result


@router.post("/{changeset_id}/reject", name="changeset_reject")
async def reject(
    changeset_id: str,
    body: RejectRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.reject(principal, changeset_id, body.reason)
    audit(request, principal, "changeset_reject", target=changeset_id)
    return result


@router.post("/{changeset_id}/apply", name="changeset_apply")
async def apply(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: EmptyRequest | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.apply(principal, changeset_id, _idempotency_key(request))
    audit(request, principal, "changeset_apply", target=changeset_id)
    return result


@router.post("/{changeset_id}/withdraw", name="changeset_withdraw")
async def withdraw(
    changeset_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: EmptyRequest | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.withdraw(principal, changeset_id)
    audit(request, principal, "changeset_withdraw", target=changeset_id)
    return result


@router.post("/{changeset_id}/rebase", name="changeset_rebase")
async def rebase(
    changeset_id: str,
    body: RebaseRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.changes.rebase(principal, changeset_id, body.base_revision)
    audit(request, principal, "changeset_rebase", target=changeset_id)
    return result
