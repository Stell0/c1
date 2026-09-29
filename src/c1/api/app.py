"""Single-process authenticated HTTP boundary for current security state."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from c1.api.problems import http_problem, problem, profile_problem, validation_problem
from c1.api.routes import (
    changesets,
    context,
    documents,
    history,
    probe,
    query,
    resources,
    security,
    software,
    system,
)
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGAError
from c1.authorization.tokens import AuthenticationError
from c1.config import Settings
from c1.context.errors import ContextError
from c1.model.diagnostics import ProfileError
from c1.query.plan import QueryPlanError
from c1.runtime import Runtime
from c1.storage.terminus import StorageError

_SELECTORS = frozenset({"database", "repository", "store", "issuer", "principal"})
_RAW_QUERY_KEYS = frozenset({"woql", "graphql", "sparql", "query"})
_MAX_BODY_BYTES = 1024 * 1024


def _query_allowed(request: Request) -> set[str]:
    path = request.url.path
    if request.method == "GET" and path.startswith("/v1/probe/resources/"):
        return {"revision"}
    if request.method == "GET" and path.startswith("/v1/resources/"):
        return {"revision"}
    if request.method == "GET" and path == "/v1/history":
        return {"resource_id", "limit", "cursor"}
    if request.method == "GET" and path == "/v1/catalog":
        return set()
    if request.method == "GET" and path == "/v1/entities":
        return {
            "types",
            "ids",
            "label",
            "label_mode",
            "alias",
            "alias_mode",
            "keywords_any",
            "keywords_all",
            "scope_ids",
            "project_ref",
            "valid_at",
            "include_unknown",
            "revision",
            "order",
            "limit",
            "cursor",
            "lifecycle",
            "review_state",
        }
    if request.method == "GET" and path == "/v1/assertions":
        return {
            "subject",
            "predicate",
            "object",
            "review_state",
            "lifecycle",
            "valid_at",
            "include_unknown",
            "revision",
            "limit",
            "cursor",
            "competing_for",
        }
    if request.method == "GET" and path in {"/v1/sources", "/v1/evidence"}:
        return {"revision", "limit", "cursor"}
    if request.method == "GET" and path == "/v1/export":
        return {"revision", "types", "limit", "cursor"}
    if request.method == "GET" and path == "/v1/documents":
        return {"revision", "title", "text_contains", "kind", "limit", "cursor"}
    if request.method == "GET" and path == "/v1/documents/by-id":
        return {"document_id", "revision"}
    if request.method == "GET" and path.startswith("/v1/documents/"):
        if path.endswith("/parts"):
            return {"revision", "text_contains", "limit", "cursor"}
        if path.endswith("/render") or path.endswith("/export"):
            return {"revision", "format"}
        if path.endswith("/history"):
            return {"limit", "cursor"}
        return {"revision"}
    if request.method == "GET" and path.startswith("/v1/entities/"):
        if path.endswith("/neighborhood"):
            return {"direction", "predicates", "depth", "limit", "cursor", "revision"}
        return {"revision"}
    if request.method == "DELETE" and "/members/" in path and path.startswith("/v1/access-scopes/"):
        return {"role"}
    return set()


def _invalid_selectors(request: Request) -> bool:
    allowed = _query_allowed(request)
    for key in request.query_params:
        if key.lower() in _SELECTORS or key not in allowed:
            return True
        if len(request.query_params.getlist(key)) != 1:
            return True
    for key in request.headers:
        lowered = key.lower()
        if lowered.startswith("x-c1-") or lowered in {
            "x-database",
            "x-repository",
            "x-store",
            "x-issuer",
            "x-principal",
        }:
            return True
    return False


def _query_problem(request: Request, *, body: object = None) -> JSONResponse:
    raw = any(key.lower() in _RAW_QUERY_KEYS for key in request.query_params)
    if isinstance(body, dict):
        raw = raw or any(str(key).lower() in _RAW_QUERY_KEYS for key in body)
    response = problem(400)
    payload = json.loads(bytes(response.body))
    payload["code"] = (
        "C1-CX-001" if request.url.path == "/v1/context" else "C1-QY-002" if raw else "C1-QY-001"
    )
    return JSONResponse(status_code=400, media_type="application/problem+json", content=payload)


def _is_query_route(request: Request) -> bool:
    path = request.url.path
    return (
        path
        in {
            "/v1/catalog",
            "/v1/context",
            "/v1/entities",
            "/v1/entities/search",
            "/v1/assertions",
            "/v1/sources",
            "/v1/evidence",
            "/v1/export",
        }
        or path.startswith("/v1/entities/")
        or path == "/v1/documents"
        or path.startswith("/v1/documents/")
    )


def _emit(
    runtime: Runtime,
    request: Request,
    *,
    principal: str = "",
    operation: str,
    outcome: str,
    reason: str = "",
) -> None:
    runtime.audit.emit(
        principal=principal,
        operation=operation,
        outcome=outcome,
        reason=reason,
        correlation_id=request.state.correlation_id,
    )


def _operation_name(request: Request) -> str:
    route = request.scope.get("route")
    name = getattr(route, "name", None)
    return str(name) if name else "request"


async def _bounded_body(request: Request) -> bytes | None:
    """Read at most 1 MiB even when Content-Length is absent or false."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            return None
        body.extend(chunk)
    return bytes(body)


class BoundaryMiddleware:
    def __init__(self, app: ASGIApp, runtime: Runtime) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        request.state.correlation_id = str(uuid.uuid4())

        async def reject(status: int) -> None:
            await problem(status)(scope, receive, send)

        public = request.method == "GET" and request.url.path == "/v1/readyz"
        if public:
            if _invalid_selectors(request):
                await reject(400)
                return
        else:
            headers = request.headers.getlist("authorization")
            if len(headers) != 1:
                _emit(
                    self.runtime,
                    request,
                    operation="authenticate",
                    outcome="denied",
                    reason="missing_bearer",
                )
                await reject(401)
                return
            scheme, separator, token = headers[0].partition(" ")
            if (
                not separator
                or scheme.lower() != "bearer"
                or not token
                or any(char.isspace() for char in token)
            ):
                _emit(
                    self.runtime,
                    request,
                    operation="authenticate",
                    outcome="denied",
                    reason="invalid_bearer",
                )
                await reject(401)
                return
            try:
                principal = await self.runtime.tokens.authenticate(token)
            except AuthenticationError:
                _emit(
                    self.runtime,
                    request,
                    operation="authenticate",
                    outcome="denied",
                    reason="invalid_token",
                )
                await reject(401)
                return
            except Exception:
                _emit(
                    self.runtime,
                    request,
                    operation="authenticate",
                    outcome="unavailable",
                    reason="identity_unavailable",
                )
                await reject(503)
                return
            request.state.principal = principal

        try:
            body = await _bounded_body(request)
        except ClientDisconnect:
            await reject(400)
            return
        if body is None:
            if not public:
                _emit(
                    self.runtime,
                    request,
                    principal=principal.id,
                    operation="request_boundary",
                    outcome="denied",
                    reason="body_too_large",
                )
            await reject(413)
            return
        if not public:
            if "x-on-behalf-of" in request.headers:
                _emit(
                    self.runtime,
                    request,
                    principal=principal.id,
                    operation="attempted_delegation",
                    outcome="ignored",
                    reason="client_header",
                )
            if body:
                try:
                    parsed: object = json.loads(body)
                except (ValueError, UnicodeError):
                    parsed = None
                if isinstance(parsed, dict) and "on_behalf_of" in parsed:
                    _emit(
                        self.runtime,
                        request,
                        principal=principal.id,
                        operation="attempted_delegation",
                        outcome="ignored",
                        reason="client_body",
                    )
            else:
                parsed = None
            if _invalid_selectors(request):
                _emit(
                    self.runtime,
                    request,
                    principal=principal.id,
                    operation="request_boundary",
                    outcome="denied",
                    reason="request_selector",
                )
                if _is_query_route(request):
                    await _query_problem(request, body=parsed)(scope, receive, send)
                else:
                    await reject(400)
                return
            if (
                _is_query_route(request)
                and isinstance(parsed, dict)
                and any(str(key).lower() in _RAW_QUERY_KEYS for key in parsed)
            ):
                await _query_problem(request, body=parsed)(scope, receive, send)
                return

        sent = False

        async def replay_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


def create_app(settings: Settings, *, runtime: Runtime | None = None) -> FastAPI:
    service = runtime if runtime is not None else Runtime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(
        title="C1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = service

    app.add_middleware(BoundaryMiddleware, runtime=service)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        _emit(
            service,
            request,
            principal=getattr(getattr(request.state, "principal", None), "id", ""),
            operation=_operation_name(request),
            outcome="denied",
            reason="invalid_request",
        )
        if _is_query_route(request):
            if any(
                "limit" in error.get("loc", ()) or "ids" in error.get("loc", ())
                for error in exc.errors()
            ):
                response = problem(422)
                payload = json.loads(bytes(response.body))
                payload["code"] = "C1-QY-010"
                return JSONResponse(
                    status_code=422,
                    media_type="application/problem+json",
                    content=payload,
                )
            return _query_problem(request, body=exc.body)
        return await validation_problem(request, exc)

    @app.exception_handler(ProfileError)
    async def profile_handler(request: Request, exc: ProfileError) -> JSONResponse:
        _emit(
            service,
            request,
            principal=getattr(getattr(request.state, "principal", None), "id", ""),
            operation=_operation_name(request),
            outcome="denied",
            reason="invalid_profile_data",
        )
        return await profile_problem(request, exc)

    @app.exception_handler(SecurityError)
    async def security_handler(request: Request, exc: SecurityError) -> JSONResponse:
        status = exc.status if exc.status in {400, 401, 403, 404, 409, 422, 503} else 503
        _emit(
            service,
            request,
            principal=getattr(getattr(request.state, "principal", None), "id", ""),
            operation=_operation_name(request),
            outcome="denied" if status < 500 else "unavailable",
            reason=exc.reason,
        )
        return problem(status)

    @app.exception_handler(QueryPlanError)
    async def query_handler(request: Request, exc: QueryPlanError) -> JSONResponse:
        _emit(
            service,
            request,
            principal=getattr(getattr(request.state, "principal", None), "id", ""),
            operation=_operation_name(request),
            outcome="unavailable" if exc.status >= 500 else "denied",
            reason=exc.reason,
        )
        response = problem(exc.status)
        payload = json.loads(bytes(response.body))
        payload["code"] = exc.code
        if isinstance(exc, ContextError):
            payload["reason"] = exc.reason
            payload.update(exc.details)
        return JSONResponse(
            status_code=exc.status, media_type="application/problem+json", content=payload
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return await http_problem(request, exc)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        operational = isinstance(
            exc, (StorageError, FGAError, httpx.HTTPError, OSError, TimeoutError)
        )
        _emit(
            service,
            request,
            principal=getattr(getattr(request.state, "principal", None), "id", ""),
            operation=_operation_name(request),
            outcome="unavailable" if operational else "failed",
            reason="backend_unavailable" if operational else "internal_error",
        )
        return problem(503 if operational else 500)

    app.include_router(system.router)
    app.include_router(security.router)
    app.include_router(changesets.router)
    app.include_router(resources.router)
    app.include_router(history.router)
    app.include_router(query.router)
    app.include_router(documents.router)
    app.include_router(context.router)
    app.include_router(software.router)
    if settings.enable_probe_routes:
        app.include_router(probe.router)
    return app
