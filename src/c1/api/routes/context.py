"""The browser, scripts and external clients share one context request path."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.context.errors import ContextError
from c1.context.request import ContextRequest
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")


@router.post("/context", name="context_build")
async def context(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    try:
        value = ContextRequest.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise ContextError(400, "C1-CX-001", "invalid_request") from exc
    result = await runtime.context.build(principal, value)
    audit(request, principal, "context_build")
    return result
