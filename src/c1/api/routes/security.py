"""Audited security administration over the configured authorization plane."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.errors import SecurityError
from c1.authorization.principal import Principal
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")

ScopeRole = Literal["reader", "contributor", "creator", "reviewer", "access_admin"]
InstanceRole = Literal["schema_admin", "access_admin", "operator"]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ScopeCreate(_StrictRequest):
    label: str
    id: str | None = None
    kind: Literal["standard", "drafting"] = "standard"


class Membership(_StrictRequest):
    member: str
    role: ScopeRole


class InstanceGrant(_StrictRequest):
    member: str
    role: InstanceRole


class Rescope(_StrictRequest):
    resource_id: str


@router.get("/access-scopes")
async def list_scopes(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, list[dict[str, Any]]]:
    scopes = await runtime.journal.list("Scope")
    visible: list[dict[str, Any]] = []
    for scope in scopes:
        scope_id = scope.get("id")
        if not isinstance(scope_id, str):
            continue
        decision = await runtime.plane.check_scope(principal, "access_admin", scope_id)
        if decision.reason == "security_unavailable":
            raise SecurityError(503, "authorization_unavailable")
        if decision.allowed:
            visible.append(scope)
    audit(request, principal, "scope_list")
    return {"access_scopes": visible}


@router.post("/access-scopes", status_code=201)
async def create_scope(
    body: ScopeCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.create_scope(
        principal, body.label, id=body.id, kind=body.kind
    )
    audit(request, principal, "scope_create", target=str(result.get("id", "")))
    return result


@router.post("/access-scopes/{scope_id:path}/members")
async def add_member(
    scope_id: str,
    body: Membership,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.membership(
        principal, scope_id, body.member, body.role, grant=True
    )
    audit(request, principal, "scope_member_grant", target=scope_id)
    return result


@router.delete("/access-scopes/{scope_id:path}/members/{member:path}")
async def remove_member(
    scope_id: str,
    member: str,
    request: Request,
    role: Annotated[ScopeRole, Query()],
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.membership(principal, scope_id, member, role, grant=False)
    audit(request, principal, "scope_member_revoke", target=scope_id)
    return result


@router.post("/access-scopes/{scope_id:path}/bindings")
async def propose_binding(
    scope_id: str,
    body: Rescope,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.propose_rescope(principal, body.resource_id, scope_id)
    audit(request, principal, "rescope_propose", target=body.resource_id)
    return result


@router.delete("/access-scopes/{scope_id:path}")
async def retire_scope(
    scope_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.retire_scope(principal, scope_id)
    audit(request, principal, "scope_retire", target=scope_id)
    return result


@router.post("/security-operations/recover")
async def recover(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    decision = await runtime.plane.check_instance(principal, "operator")
    if not decision.allowed:
        raise SecurityError(
            503 if decision.reason == "security_unavailable" else 403,
            "operator_required",
        )
    await runtime.operations.recover()
    await runtime.changes.recover()
    audit(request, principal, "security_recover")
    return {"status": "recovered"}


@router.post("/security-operations/{operation_id:path}/approve")
async def approve(
    operation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.approve(principal, operation_id)
    audit(request, principal, "rescope_approve", target=operation_id)
    return result


@router.post("/security-operations/{operation_id:path}/apply")
async def apply(
    operation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.apply(principal, operation_id)
    audit(request, principal, "security_apply", target=operation_id)
    return result


@router.get("/security-operations/{operation_id:path}")
async def get_operation(
    operation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.get_operation(principal, operation_id)
    audit(request, principal, "security_operation_read", target=operation_id)
    return result


@router.post("/instance/grants")
async def grant_instance(
    body: InstanceGrant,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await runtime.operations.instance_grant(principal, body.member, body.role, grant=True)
    audit(request, principal, "instance_grant", target=body.member)
    return result
