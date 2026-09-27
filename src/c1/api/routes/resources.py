"""Current and historical reads under the runtime's current-binding gate."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.errors import SecurityError
from c1.authorization.principal import Principal
from c1.runtime import Runtime

router = APIRouter(prefix="/v1/resources")


@router.get("/{resource_id:path}", name="resource_read")
async def read_resource(
    resource_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    revision: str | None = None,
) -> dict[str, Any]:
    record = await runtime.read(principal, resource_id, revision=revision)
    if record is None:
        raise SecurityError(404, "not_found")
    audit(request, principal, "resource_read", target=resource_id)
    return record.model_dump(mode="json")
