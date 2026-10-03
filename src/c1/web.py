"""One process serving the unchanged ``/v1`` API and, optionally, the Explorer (M12 D1).

``/explorer`` requests go to the Explorer; everything else goes to the API app
with its own boundary middleware. The Explorer reaches the API only through an
in-process ASGI client that carries the signed-in person's access token.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from c1.api.app import create_app
from c1.config import ExplorerSettings, Settings
from c1.explorer.app import create_explorer
from c1.runtime import Runtime


class WebApp:
    def __init__(self, api: FastAPI, explorer: Any) -> None:
        self.api, self.explorer = api, explorer
        self.state = api.state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        path = scope.get("path", "")
        if path == "/explorer" or path.startswith("/explorer/"):
            await self.explorer(scope, receive, send)
        else:
            await self.api(scope, receive, send)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        stack = AsyncExitStack()
        message = await receive()
        assert message["type"] == "lifespan.startup"
        try:
            await stack.enter_async_context(self.api.router.lifespan_context(self.api))
            await stack.enter_async_context(self.explorer.router.lifespan_context(self.explorer))
        except BaseException:
            await stack.aclose()
            await send({"type": "lifespan.startup.failed", "message": "startup failed"})
            return
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        await stack.aclose()
        await send({"type": "lifespan.shutdown.complete"})


def create_web_app(
    settings: Settings,
    explorer_settings: ExplorerSettings | None,
    *,
    runtime: Runtime | None = None,
) -> ASGIApp:
    api = create_app(settings, runtime=runtime)
    if explorer_settings is None:
        return api
    return WebApp(api, create_explorer(settings, explorer_settings, api))
