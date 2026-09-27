"""Authenticated deterministic query routes over the shared repository."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.model.ids import validate_iri
from c1.query.filters import AssertionFilters, QueryFilters
from c1.query.plan import QueryPlanError
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")
_REVISION = re.compile(r"(?:branch:|commit:)?[A-Za-z0-9_-]{1,128}\Z")


def _csv(value: str | None) -> list[str]:
    return [part for part in (value or "").split(",") if part]


def _revision(value: str | None) -> str | None:
    if value is not None and not _REVISION.fullmatch(value):
        raise QueryPlanError(400, "C1-QY-001", "invalid_revision")
    return value


def _limit(value: str | None, *, maximum: int = 200) -> int:
    try:
        parsed = int(value or "50")
    except ValueError as exc:
        raise QueryPlanError(400, "C1-QY-001", "invalid_limit") from exc
    if not 1 <= parsed <= maximum:
        raise QueryPlanError(422, "C1-QY-010", "limit_exceeded")
    return parsed


def _bool(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise QueryPlanError(400, "C1-QY-001", "invalid_boolean")
    return value.lower() == "true"


async def _bounded(runtime: Runtime, work: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        async with asyncio.timeout(runtime.settings.query_time_budget_ms / 1000):
            return await work
    except TimeoutError as exc:
        raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc


def _entity_filters(request: Request) -> QueryFilters:
    params = request.query_params
    body: dict[str, Any] = {}
    for key in ("types", "ids", "scope_ids", "lifecycle", "review_state"):
        if key in params:
            body[key] = _csv(params.get(key))
    if len(body.get("ids", [])) > 200:
        raise QueryPlanError(422, "C1-QY-010", "ids_limit_exceeded")
    for key in ("keywords_any", "keywords_all"):
        if key in params:
            body[key] = [{"text": value} for value in _csv(params.get(key))]
    for key in ("label", "alias"):
        if key in params:
            body[key] = {
                "text": params[key],
                "mode": params.get(key + "_mode", "exact"),
            }
    for key in ("project_ref", "valid_at", "revision", "order", "cursor"):
        if key in params:
            body[key] = params[key]
    for key in ("include_unknown",):
        if key in params:
            body[key] = _bool(params[key])
    if "limit" in params:
        body["limit"] = _limit(params["limit"])
    try:
        return QueryFilters.model_validate(body)
    except ValidationError as exc:
        raise QueryPlanError(400, "C1-QY-001", "invalid_filter") from exc


def _assertion_filters(request: Request) -> AssertionFilters:
    params = request.query_params
    body: dict[str, Any] = {
        key: params[key]
        for key in ("subject", "predicate", "object", "valid_at", "revision", "limit", "cursor")
        if key in params
    }
    if "limit" in body:
        body["limit"] = _limit(str(body["limit"]))
    for key in ("review_state", "lifecycle"):
        if key in params:
            body[key] = _csv(params.get(key))
    if "include_unknown" in params:
        body["include_unknown"] = _bool(params["include_unknown"])
    if "competing_for" in params:
        try:
            subject, predicate = params["competing_for"].split(",", 1)
            body["subject"], body["predicate"] = subject, predicate
        except ValueError as exc:
            raise QueryPlanError(400, "C1-QY-001", "invalid_filter") from exc
    try:
        return AssertionFilters.model_validate(body)
    except ValidationError as exc:
        raise QueryPlanError(400, "C1-QY-001", "invalid_filter") from exc


@router.get("/catalog", name="query_catalog")
async def catalog(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(runtime, runtime.query.catalog(principal))
    audit(request, principal, "query_catalog")
    return result


@router.get("/entities", name="query_entities")
async def entities(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(runtime, runtime.query.entities(principal, _entity_filters(request)))
    audit(request, principal, "query_entities")
    return result


@router.post("/entities/search", name="query_entities_search")
async def search_entities(
    body: QueryFilters,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(runtime, runtime.query.entities(principal, body))
    audit(request, principal, "query_entities_search")
    return result


@router.get("/assertions", name="query_assertions")
async def assertions(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime, runtime.query.assertions(principal, _assertion_filters(request))
    )
    audit(request, principal, "query_assertions")
    return result


@router.get("/sources", name="query_sources")
async def sources(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.query.list_kind(
            principal,
            "Source",
            revision=_revision(request.query_params.get("revision")),
            limit=_limit(request.query_params.get("limit")),
            cursor=request.query_params.get("cursor"),
        ),
    )
    audit(request, principal, "query_sources")
    return result


@router.get("/evidence", name="query_evidence")
async def evidence(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    result = await _bounded(
        runtime,
        runtime.query.list_kind(
            principal,
            "Evidence",
            revision=_revision(request.query_params.get("revision")),
            limit=_limit(request.query_params.get("limit")),
            cursor=request.query_params.get("cursor"),
        ),
    )
    audit(request, principal, "query_evidence")
    return result


@router.get("/export", name="query_export")
async def export(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    values = _csv(request.query_params.get("types"))
    try:
        types = tuple(validate_iri(value) for value in values)
    except ValueError as exc:
        raise QueryPlanError(400, "C1-QY-001", "invalid_filter") from exc
    result = await _bounded(
        runtime,
        runtime.query.export(
            principal,
            revision=_revision(request.query_params.get("revision")),
            types=types,
            limit=_limit(request.query_params.get("limit")),
            cursor=request.query_params.get("cursor"),
        ),
    )
    audit(request, principal, "query_export")
    return result


@router.get("/entities/{resource_id:path}", name="query_entity_read")
async def read_entity(
    resource_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    if resource_id.endswith("/neighborhood"):
        identifier = resource_id.removesuffix("/neighborhood")
        params = request.query_params
        predicates = frozenset(_csv(params.get("predicates")))
        try:
            if not predicates or any(
                predicate not in runtime.registry.predicates for predicate in predicates
            ):
                raise ValueError("undeclared predicate")
            result = await _bounded(
                runtime,
                runtime.query.neighborhood(
                    principal,
                    identifier,
                    predicates=predicates,
                    direction=params.get("direction", "out"),
                    depth=_limit(params.get("depth", "1"), maximum=3),
                    limit=_limit(params.get("limit", "200"), maximum=2000),
                    revision=_revision(params.get("revision")),
                    cursor=params.get("cursor"),
                ),
            )
        except ValueError as exc:
            raise QueryPlanError(400, "C1-QY-001", "invalid_filter") from exc
        audit(request, principal, "query_neighborhood", target=identifier)
        return result
    try:
        validate_iri(resource_id)
    except ValueError as exc:
        raise QueryPlanError(400, "C1-QY-001", "invalid_iri") from exc
    result = await _bounded(
        runtime,
        runtime.query.entity(
            principal, resource_id, revision=_revision(request.query_params.get("revision"))
        ),
    )
    audit(request, principal, "query_entity_read", target=resource_id)
    return result
