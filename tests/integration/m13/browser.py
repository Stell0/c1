"""Headless Chromium against the reference TLS endpoint (M13 D3).

Host names resolve to the loopback proxy with `--host-resolver-rules`. The test
server certificate is pinned by its SPKI hash; certificate errors are not
ignored in general.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from playwright.async_api import Browser, Page, async_playwright

from tests.browser.harness import BROWSERS, Person, Recorder
from tests.integration.m13.reference import BASE, DIR


def spki_hash(certificate: Path) -> str:
    cert = x509.load_pem_x509_certificate(certificate.read_bytes())
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(spki)
    return base64.b64encode(digest.finalize()).decode()


@asynccontextmanager
async def browser(port: int = 18443, directory: Path = DIR) -> AsyncIterator[Browser]:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS))
    pin = spki_hash(directory / "certs/server.pem")
    async with async_playwright() as playwright:
        instance = await playwright.chromium.launch(
            args=[
                "--host-resolver-rules=MAP c1.test 127.0.0.1, MAP auth.c1.test 127.0.0.1",
                f"--ignore-certificate-errors-spki-list={pin}",
            ]
        )
        try:
            yield instance
        finally:
            await instance.close()


async def sign_in(instance: Browser, name: str, password: str, *, base: str = BASE) -> Person:
    context = await instance.new_context()
    context.set_default_timeout(180_000)
    page: Page = await context.new_page()
    recorder = Recorder()
    recorder.attach(page)
    await page.goto(base + "/explorer/")
    await page.fill("#username", name)
    await page.fill("#password", password)
    await page.click("#kc-login")
    await page.wait_for_url(base + "/explorer/**")
    if "/explorer/callback" in page.url:
        await page.wait_for_url(lambda url: "/explorer/callback" not in url)
    await recorder.settle()
    return Person(name, context, page, recorder)
