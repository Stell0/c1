"""M12 browser harness: the case's API plus the Explorer on a real loopback port.

The served app is the same ``c1.web.WebApp`` composition as production. The
case already runs the API runtime, so the server runs with lifespan off and
only the Explorer's own resources are opened here.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from playwright.async_api import Browser, BrowserContext, Page, Response, async_playwright

from c1.config import ExplorerSettings
from c1.explorer.app import create_explorer
from c1.web import WebApp
from probes.config import ROOT, environment

HOST = "127.0.0.1"
PORT = 18095
ORIGIN = f"http://{HOST}:{PORT}"
BROWSERS = ROOT / ".playwright"


def browser_enabled() -> bool:
    return os.environ.get("C1_STACK") == "1" and os.environ.get("C1_BROWSER") == "1"


@dataclass
class Captured:
    url: str
    status: int
    headers: dict[str, str]
    body: str


@dataclass
class Recorder:
    """Every response a page received: status, headers and body text (T03, T05)."""

    responses: list[Captured] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    dialogs: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    _pending: list[asyncio.Task[None]] = field(default_factory=list)

    def attach(self, page: Page) -> None:
        page.on("request", lambda request: self.requests.append(request.url))
        page.on(
            "response",
            lambda response: self._pending.append(asyncio.ensure_future(self._record(response))),
        )
        page.on("dialog", lambda dialog: self._dismiss(dialog))
        page.on("download", lambda download: self.downloads.append(download.url))

    def _dismiss(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        asyncio.ensure_future(dialog.dismiss())

    async def _record(self, response: Response) -> None:
        try:
            body = (await response.body()).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        self.responses.append(
            Captured(response.url, response.status, dict(await response.all_headers()), body)
        )

    async def settle(self) -> None:
        while self._pending:
            pending, self._pending = self._pending, []
            await asyncio.gather(*pending, return_exceptions=True)

    def explorer_responses(self) -> list[Captured]:
        return [r for r in self.responses if r.url.startswith(ORIGIN + "/explorer")]

    def everything(self) -> str:
        """All captured bytes as text, including headers, for sentinel searches."""
        parts = []
        for item in self.responses:
            parts.append(item.url)
            parts.extend(f"{k}: {v}" for k, v in item.headers.items())
            parts.append(item.body)
        return "\n".join(parts)


@asynccontextmanager
async def explorer_server(case: Any) -> AsyncIterator[str]:
    secret = environment().get("C1_EXPLORER_CLIENT_SECRET")
    if not secret:
        raise RuntimeError("C1_EXPLORER_CLIENT_SECRET is missing; rerun make stack-up")
    settings = ExplorerSettings(origin=ORIGIN, client_id="c1-explorer", client_secret=secret)
    explorer = create_explorer(case.settings, settings, case.app)
    web = WebApp(case.app, explorer)
    server = uvicorn.Server(
        uvicorn.Config(
            web, host=HOST, port=PORT, lifespan="off", log_level="warning", access_log=False
        )
    )
    async with explorer.router.lifespan_context(explorer):
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                if task.done():
                    task.result()
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("Explorer test server did not start")
            yield ORIGIN
        finally:
            server.should_exit = True
            await task


@asynccontextmanager
async def browser() -> AsyncIterator[Browser]:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS))
    async with async_playwright() as playwright:
        instance = await playwright.chromium.launch()
        try:
            yield instance
        finally:
            await instance.close()


@dataclass
class Person:
    name: str
    context: BrowserContext
    page: Page
    recorder: Recorder

    async def goto(self, path: str) -> Response | None:
        response = await self.page.goto(ORIGIN + path)
        await self.recorder.settle()
        return response

    async def text(self, selector: str) -> str:
        return (await self.page.locator(selector).first.inner_text()).strip()

    async def field(self, name: str) -> str:
        return await self.text(f'[data-field="{name}"]')


async def sign_in(instance: Browser, name: str, *, path: str = "/explorer/") -> Person:
    """Sign in through Keycloak's real login form with the user's synthetic password."""
    password = environment().get(f"C1_USER_{name.upper()}_PASSWORD")
    if not password:
        raise RuntimeError(f"password for {name} is missing")
    context = await instance.new_context()
    page = await context.new_page()
    recorder = Recorder()
    recorder.attach(page)
    await page.goto(ORIGIN + path)
    await page.fill("#username", name)
    await page.fill("#password", password)
    await page.click("#kc-login")
    await page.wait_for_url(ORIGIN + "/explorer/**", timeout=30_000)
    await page.wait_for_load_state("load")
    if page.url.startswith(ORIGIN + "/explorer/callback"):
        await page.wait_for_url(lambda url: "/explorer/callback" not in url, timeout=30_000)
    await recorder.settle()
    return Person(name, context, page, recorder)


def evidence_dir() -> Path:
    path = ROOT / "docs/evidence/M12"
    path.mkdir(parents=True, exist_ok=True)
    return path
