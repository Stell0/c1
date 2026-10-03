"""Explorer application: sign-in, sessions, and the request wrapper for every page (M12)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from c1.config import ExplorerSettings, Settings
from c1.explorer.client import ApiClient, ApiFailure, ApiResponse
from c1.explorer.oidc import LoginError, OIDCClient
from c1.explorer.render import Renderer
from c1.explorer.security import SECURITY_HEADERS, FormError, parse_form, same_origin, single
from c1.explorer.sessions import Session, SessionStore, csrf_matches

REFRESH_MARGIN_S = 30
# Loopback HTTP is a potentially trustworthy origin, so browsers accept Secure
# cookies there; the __Host- prefix and Secure apply on every origin (D3).
SESSION_COOKIE = "__Host-c1_session"
LOGIN_COOKIE = "__Host-c1_login"
_STATIC = Path(__file__).resolve().parent / "static"


@dataclass
class Explorer:
    settings: Settings
    explorer: ExplorerSettings
    api: ApiClient
    oidc: OIDCClient
    sessions: SessionStore
    renderer: Renderer


@dataclass
class Ctx:
    """One authenticated Explorer request."""

    app: Explorer
    request: Request
    session: Session
    form: dict[str, list[str]] = field(default_factory=dict)

    async def api(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        return await self.app.api.call(
            self.session.tokens.access_token,
            method,
            path,
            params={k: v for k, v in (params or {}).items() if v not in ("", None)},
            json=json,
            idempotency_key=idempotency_key,
        )

    def arg(self, name: str, default: str = "") -> str:
        values = self.request.query_params.getlist(name)
        if len(values) > 1:
            raise FormError("duplicate_field")
        return values[0] if values else default

    def field(self, name: str, *, required: bool = True) -> str:
        return single(self.form, name, required=required)

    def fields(self, name: str) -> list[str]:
        return list(self.form.get(name, []))

    async def page(self, template: str, *, status: int = 200, **context: Any) -> Response:
        instance = await self.api("GET", "/v1/instance")
        banner = instance.body if instance.ok and isinstance(instance.body, dict) else None
        html = self.app.renderer.render(
            template,
            banner=banner,
            user=self.session.display_name or self.session.subject,
            csrf=self.session.csrf,
            **context,
        )
        return secured(HTMLResponse(html, status_code=status))

    async def problem(self, response: ApiResponse, *, title: str) -> Response:
        """Show an API refusal without changing its meaning (D8)."""
        return await self.page(
            "problem.html",
            status=response.status if response.status >= 400 else 502,
            title=title,
            status_code=response.status,
            code=response.code,
            detail=problem_text(response),
        )


def problem_text(response: ApiResponse) -> str:
    if response.status == 404:
        return "Not found, or not available to you."
    if response.status == 403:
        return "The C1 API refused this action for your account."
    if response.status == 401:
        return "Your sign-in is no longer accepted. Sign in again."
    if response.status == 409:
        if response.code == "C1-CX-011":
            return "The underlying data or your access changed. Restart from the first page."
        return "The data changed since this page was loaded, or the request conflicts. Restart."
    if response.status == 422:
        return "The C1 API rejected the request as invalid."
    if response.status == 400:
        return "The C1 API rejected the request."
    if response.status >= 500:
        return "The service is not ready. Try again later."
    return "The request did not complete."


def secured(response: Response) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


def _safe_return(path: str) -> str:
    """Only an Explorer-relative path may be a post-login destination."""
    parts = urlsplit(path)
    if (
        parts.scheme
        or parts.netloc
        or not parts.path.startswith("/explorer/")
        or parts.path.startswith("//")
        or "\\" in path
        or len(path) > 2048
    ):
        return "/explorer/"
    return path


View = Callable[[Ctx], Awaitable[Response]]


def view(explorer: Explorer, handler: View, *, post: bool = False) -> Callable[[Request], Any]:
    """Session, CSRF, origin and token-freshness checks around one page (D3, D4)."""

    async def endpoint(request: Request) -> Response:
        session = explorer.sessions.get(request.cookies.get(SESSION_COOKIE))
        if post:
            if not same_origin(request.headers, explorer.explorer.origin):
                return secured(HTMLResponse("Forbidden: cross-origin request", status_code=403))
            if session is None:
                return secured(HTMLResponse("Forbidden: not signed in", status_code=403))
            try:
                form = parse_form(await request.body(), request.headers.get("content-type"))
                token = single(form, "csrf")
            except FormError:
                return secured(HTMLResponse("Bad request: invalid form", status_code=400))
            if not csrf_matches(session, token):
                return secured(HTMLResponse("Forbidden: invalid form token", status_code=403))
        else:
            form = {}
            if session is None:
                target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return secured(
                    RedirectResponse(
                        "/explorer/login?" + _encode({"next": _safe_return(target)}),
                        status_code=303,
                    )
                )
        if session.tokens.access_expires_at - time.monotonic() < REFRESH_MARGIN_S:
            try:
                session.tokens = await explorer.oidc.refresh(session.tokens)
            except LoginError:
                explorer.sessions.delete(request.cookies.get(SESSION_COOKIE))
                response = RedirectResponse("/explorer/login", status_code=303)
                return secured(response)
        ctx = Ctx(explorer, request, session, form)
        try:
            return await handler(ctx)
        except ApiFailure as failure:
            return await ctx.problem(failure.response, title="Request failed")
        except FormError as error:
            return await ctx.page(
                "problem.html",
                status=400,
                title="Invalid input",
                status_code=400,
                code=str(error),
                detail="The form or address contained invalid input.",
            )

    return endpoint


def _encode(params: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(params)


def _cookie(response: Response, explorer: Explorer, name: str, value: str, **kwargs: Any) -> None:
    response.set_cookie(
        name,
        value,
        path="/",
        secure=True,
        httponly=True,
        **kwargs,
    )


def _expire(response: Response, name: str) -> None:
    """A __Host- cookie is only replaced by a Secure, Path=/ Set-Cookie."""
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


async def login(explorer: Explorer, request: Request) -> Response:
    target = _safe_return(request.query_params.get("next", "/explorer/"))
    handle, transaction = explorer.sessions.begin_login(target)
    try:
        url = await explorer.oidc.authorization_url(transaction)
    except LoginError:
        return secured(HTMLResponse(_plain_page("Sign-in is unavailable."), status_code=503))
    response = RedirectResponse(url, status_code=303)
    _cookie(response, explorer, LOGIN_COOKIE, handle, samesite="lax", max_age=300)
    return secured(response)


async def callback(explorer: Explorer, request: Request) -> Response:
    params = request.query_params
    transaction = explorer.sessions.finish_login(
        request.cookies.get(LOGIN_COOKIE), params.get("state")
    )
    failed = secured(HTMLResponse(_plain_page("Sign-in failed. Start again."), status_code=400))
    _expire(failed, LOGIN_COOKIE)
    if transaction is None or "error" in params or len(params.getlist("code")) != 1:
        return failed
    try:
        tokens, claims = await explorer.oidc.exchange(params["code"], transaction)
    except LoginError:
        return failed
    name = claims.get("preferred_username")
    session_id = explorer.sessions.create(
        tokens,
        subject=str(claims.get("sub", "")),
        display_name=name if isinstance(name, str) else "",
    )
    # A same-site continuation page, not a redirect: a navigation started by a
    # cross-site redirect would not carry the SameSite=Strict session cookie (D3).
    html = explorer.renderer.render("continue.html", target=transaction.return_to)
    response = secured(HTMLResponse(html))
    _expire(response, LOGIN_COOKIE)
    _cookie(response, explorer, SESSION_COOKIE, session_id, samesite="strict")
    return response


async def logout(explorer: Explorer, request: Request) -> Response:
    if not same_origin(request.headers, explorer.explorer.origin):
        return secured(HTMLResponse("Forbidden: cross-origin request", status_code=403))
    session_id = request.cookies.get(SESSION_COOKIE)
    session = explorer.sessions.get(session_id)
    try:
        form = parse_form(await request.body(), request.headers.get("content-type"))
        token = single(form, "csrf")
    except FormError:
        return secured(HTMLResponse("Bad request: invalid form", status_code=400))
    if session is None or not csrf_matches(session, token):
        return secured(HTMLResponse("Forbidden: invalid form token", status_code=403))
    explorer.sessions.delete(session_id)
    await explorer.oidc.logout(session.tokens)
    response = secured(HTMLResponse(explorer.renderer.render("signed_out.html")))
    _expire(response, SESSION_COOKIE)
    return response


def _plain_page(message: str) -> str:
    from html import escape

    return (
        "<!doctype html><html lang=en><meta charset=utf-8><title>C1 Explorer</title>"
        f"<main><h1>C1 Explorer</h1><p>{escape(message)}</p>"
        '<p><a href="/explorer/">Return to the Explorer</a></p></main></html>'
    )


async def static(request: Request) -> Response:
    if request.path_params["name"] != "explorer.css":
        return secured(HTMLResponse("Not found", status_code=404))
    response = FileResponse(_STATIC / "explorer.css", media_type="text/css")
    return secured(response)


def create_explorer(
    settings: Settings, explorer_settings: ExplorerSettings, api_app: ASGIApp
) -> Starlette:
    from c1.explorer import pages

    explorer = Explorer(
        settings=settings,
        explorer=explorer_settings,
        api=ApiClient(api_app),
        oidc=OIDCClient(settings.issuer, explorer_settings, timeout_s=settings.backend_timeout_s),
        sessions=SessionStore(
            idle_s=explorer_settings.session_idle_s, max_s=explorer_settings.session_max_s
        ),
        renderer=Renderer(instance_base_hint=settings.instance_base),
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await explorer.api.close()
            await explorer.oidc.close()

    async def login_endpoint(request: Request) -> Response:
        return await login(explorer, request)

    async def callback_endpoint(request: Request) -> Response:
        return await callback(explorer, request)

    async def logout_endpoint(request: Request) -> Response:
        return await logout(explorer, request)

    async def root_redirect(_request: Request) -> Response:
        return secured(RedirectResponse("/explorer/", status_code=308))

    routes = [
        Route("/explorer", root_redirect),
        Route("/explorer/login", login_endpoint),
        Route("/explorer/callback", callback_endpoint),
        Route("/explorer/logout", logout_endpoint, methods=["POST"]),
        Route("/explorer/static/{name}", static),
    ]
    for path, handler, post in pages.ROUTES:
        routes.append(
            Route(
                path,
                view(explorer, handler, post=post),
                methods=["POST"] if post else ["GET"],
            )
        )
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.explorer = explorer
    return app
