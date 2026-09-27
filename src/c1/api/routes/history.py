"""Authorized resource commit history with bounded, rechecked pages."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.errors import SecurityError
from c1.authorization.principal import Principal
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")


@router.get("/history", name="resource_history")
async def resource_history(
    request: Request,
    resource_id: Annotated[str, Query(min_length=1)],
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    result = await runtime.changes.history(principal, resource_id, limit, cursor)
    if result is None:
        raise SecurityError(404, "not_found")
    audit(request, principal, "resource_history", target=resource_id)
    return result
