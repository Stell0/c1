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
from c1.api.routes import probe, security, system
from c1.authorization.errors import SecurityError
from c1.authorization.fga import FGAError
from c1.authorization.tokens import AuthenticationError
from c1.config import Settings
from c1.model.diagnostics import ProfileError
from c1.runtime import Runtime
from c1.storage.terminus import StorageError

_SELECTORS = frozenset({"database", "repository", "store", "issuer", "principal"})
_MAX_BODY_BYTES = 1024 * 1024


def _query_allowed(request: Request) -> set[str]:
    path = request.url.path
    if request.method == "GET" and path.startswith("/v1/probe/resources/"):
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
            if _invalid_selectors(request):
                _emit(
                    self.runtime,
                    request,
                    principal=principal.id,
                    operation="request_boundary",
                    outcome="denied",
                    reason="request_selector",
                )
                await reject(400)
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
    if settings.enable_probe_routes:
        app.include_router(probe.router)
    return app
