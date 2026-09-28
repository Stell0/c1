"""Document reconstruction, search, rendering, export, and history routes."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.query.plan import QueryPlanError
from c1.runtime import Runtime

router = APIRouter(prefix="/v1/documents")
_REVISION = re.compile(r"(?:branch:|commit:)?[A-Za-z0-9_-]{1,128}\Z")


def _revision(value: str | None) -> str | None:
    if value is not None and not _REVISION.fullmatch(value):
        raise QueryPlanError(400, "C1-DC-011", "invalid_revision")
    return value


def _limit(value: str | None, maximum: int = 200, default: int = 50) -> int:
    try:
        number = int(value or str(default))
    except ValueError as exc:
        raise QueryPlanError(400, "C1-DC-008", "invalid_limit") from exc
    if not 1 <= number <= maximum:
        raise QueryPlanError(422, "C1-DC-008", "invalid_limit")
    return number


async def _bounded(runtime: Runtime, work: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        async with asyncio.timeout(runtime.settings.query_time_budget_ms / 1000):
            return await work
    except TimeoutError as exc:
        raise QueryPlanError(503, "C1-DC-012", "time_budget") from exc


@router.get("", name="documents_list")
async def documents_list(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    params = request.query_params
    result = await _bounded(
        runtime,
        runtime.documents.list(
            principal,
            revision=_revision(params.get("revision")),
            title=params.get("title"),
            text_contains=params.get("text_contains"),
            kind=params.get("kind"),
            limit=_limit(params.get("limit")),
            cursor=params.get("cursor"),
        ),
    )
    audit(request, principal, "documents_list")
    return result


@router.get("/by-id", name="document_read_by_id")
async def document_read_by_id(
    document_id: Annotated[str, Query(min_length=1)],
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    """Read an IRI without interpreting its final segment as an operation."""
    return await document_read(document_id, request, principal, runtime)


@router.get("/{document_id:path}/parts", name="document_parts")
async def document_parts(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    params = request.query_params
    result = await _bounded(
        runtime,
        runtime.documents.parts(
            principal,
            document_id,
            revision=_revision(params.get("revision")),
            text_contains=params.get("text_contains"),
            limit=_limit(params.get("limit")),
            cursor=params.get("cursor"),
        ),
    )
    audit(request, principal, "document_parts", target=document_id)
    return result


@router.get("/{document_id:path}/render", name="document_render")
async def document_render(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.documents.render(
            principal,
            document_id,
            revision=_revision(request.query_params.get("revision")),
            format=request.query_params.get("format", "markdown"),
        ),
    )
    audit(request, principal, "document_render", target=document_id)
    return result


@router.get("/{document_id:path}/export", name="document_export")
async def document_export(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.documents.export(
            principal,
            document_id,
            revision=_revision(request.query_params.get("revision")),
            format=request.query_params.get("format", "jsonld"),
        ),
    )
    audit(request, principal, "document_export", target=document_id)
    return result


@router.get("/{document_id:path}/history", name="document_history")
async def document_history(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.documents.history(
            principal,
            document_id,
            limit=_limit(request.query_params.get("limit"), maximum=100, default=20),
            cursor=request.query_params.get("cursor"),
        ),
    )
    audit(request, principal, "document_history", target=document_id)
    return result


@router.get("/{document_id:path}", name="document_read")
async def document_read(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.documents.detail(
            principal, document_id, revision=_revision(request.query_params.get("revision"))
        ),
    )
    audit(request, principal, "document_read", target=document_id)
    return result
