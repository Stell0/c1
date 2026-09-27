"""Disabled-by-default synthetic publication surface for M03 security proofs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.model.nodes import NodeRecord
from c1.runtime import Runtime

router = APIRouter(prefix="/v1/probe")
_PROBE_BASE = "urn:c1:probe:"
_FORBIDDEN = frozenset({"access_scope_id", "bound_to", "grants"})


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProbeProvision(_StrictRequest):
    record: NodeRecord
    scope_id: str | None = None
    inherited_from: str | None = None


class ProbeRevision(_StrictRequest):
    record: NodeRecord


def _valid_record(record: NodeRecord) -> bool:
    if not record.id.startswith(_PROBE_BASE):
        return False
    for predicate in record.properties:
        name = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
        if name in _FORBIDDEN:
            return False
    return True


@router.post("/resources", status_code=201)
async def provision(
    body: ProbeProvision,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    if not _valid_record(body.record):
        raise HTTPException(status_code=400)
    result = await runtime.operations.provision(
        principal, body.record, scope_id=body.scope_id, inherited_from=body.inherited_from
    )
    audit(request, principal, "probe_provision", target=body.record.id)
    return result


@router.get("/resources/{resource_id:path}")
async def read(
    resource_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    revision: str | None = None,
) -> dict[str, Any]:
    if not resource_id.startswith(_PROBE_BASE):
        audit(
            request,
            principal,
            "probe_read",
            target=resource_id,
            outcome="denied",
            reason="not_found",
        )
        raise HTTPException(status_code=404)
    record = await runtime.read(principal, resource_id, revision=revision)
    if record is None:
        audit(
            request,
            principal,
            "probe_read",
            target=resource_id,
            outcome="denied",
            reason="not_found",
        )
        raise HTTPException(status_code=404)
    audit(request, principal, "probe_read", target=resource_id)
    return record.model_dump(mode="json")


@router.put("/resources/{resource_id:path}")
async def revise(
    resource_id: str,
    body: ProbeRevision,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    if not resource_id.startswith(_PROBE_BASE) or not _valid_record(body.record):
        raise HTTPException(status_code=400)
    if body.record.id != resource_id:
        raise HTTPException(status_code=400)
    result = await runtime.operations.revise_probe(principal, resource_id, body.record)
    audit(request, principal, "probe_revision", target=resource_id)
    return result
