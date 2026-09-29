"""Target resolution and target-pinned lookup routes (M08 D9)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.query.plan import QueryPlanError
from c1.runtime import Runtime

router = APIRouter(prefix="/v1/software")


async def _bounded(runtime: Runtime, work: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        async with asyncio.timeout(runtime.settings.query_time_budget_ms / 1000):
            return await work
    except TimeoutError as exc:
        raise QueryPlanError(503, "C1-SW-007", "time_budget") from exc


@router.post("/targets/resolve", name="software_target_resolve")
async def resolve_target(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    revision = body.pop("revision", None) if isinstance(body, dict) else None
    result = await _bounded(runtime, runtime.software.resolve(principal, body, revision))
    audit(request, principal, "software_target_resolve")
    return result


@router.post("/lookup", name="software_lookup")
async def lookup(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    result = await _bounded(runtime, runtime.software.lookup(principal, body))
    audit(request, principal, "software_lookup")
    return result
