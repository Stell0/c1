"""Health, readiness, instance identity, and authenticated principal details."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from c1.api.deps import audit, get_principal, get_runtime
from c1.api.problems import problem
from c1.authorization.errors import SecurityError
from c1.authorization.principal import Principal
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")


class _WhoAmIBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    on_behalf_of: str | None = None


@router.get("/readyz")
async def readyz(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Any:
    try:
        ready = await runtime.ready()
    except Exception:
        ready = False
    if not ready:
        return problem(503)
    return {"ready": True}


@router.get("/healthz")
async def healthz(
    request: Request, principal: Annotated[Principal, Depends(get_principal)]
) -> dict[str, str]:
    audit(request, principal, "healthz")
    return {"status": "ok"}


@router.get("/instance")
async def instance(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, str]:
    if not await runtime.ready():
        raise SecurityError(503, "repository_unavailable")
    revision = await runtime.knowledge.head()
    if not await runtime.ready():
        raise SecurityError(503, "repository_unavailable")
    audit(request, principal, "instance_read", target=runtime.settings.instance_id)
    return {
        "instance_id": runtime.settings.instance_id,
        "instance_base": runtime.settings.instance_base,
        "knowledge_revision": revision,
    }


@router.get("/whoami")
async def whoami(
    request: Request, principal: Annotated[Principal, Depends(get_principal)]
) -> dict[str, str]:
    body = await request.body()
    if body:
        try:
            parsed: object = json.loads(body)
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400)
            _WhoAmIBody.model_validate(parsed)
        except (ValueError, ValidationError):
            raise HTTPException(status_code=400) from None
    audit(request, principal, "whoami")
    return {
        "issuer_alias": principal.issuer_alias,
        "subject": principal.subject,
        "kind": principal.kind,
    }
