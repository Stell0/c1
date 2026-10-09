"""Real Hydra tokens, Chromium cookies, refresh, expiry and logout."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, sync_playwright

from tests.integration.m14c.conftest import External


def login(page: Page, origin: str) -> None:
    page.goto(origin + "/explorer/login")
    page.get_by_label("User", exact=True).fill("approved")
    page.get_by_label("Password", exact=True).fill("synthetic-test-password")
    page.get_by_role("button", name="Sign in", exact=True).click()


@pytest.mark.parametrize("refresh", [False, True])
def test_t05_refresh_expiry_and_local_logout(tmp_path: Path, refresh: bool) -> None:
    tmp_path.chmod(0o700)
    fixture = External(tmp_path)
    fixture.env["C1_EXPLORER_LOGOUT_MODE"] = "local"
    fixture.env["C1_EXPLORER_SCOPES"] = "openid offline_access" if refresh else "openid"
    # Hydra's Basic client authentication must decode the OAuth form-encoded
    # credential, including reserved characters; this is not a UI export.
    fixture.env["C1_EXPLORER_CLIENT_SECRET"] = "synthetic:plus+space %"  # pragma: allowlist secret
    fixture.client_options = {
        "authorization_code_grant_access_token_lifespan": "15s",
        "refresh_token_grant_access_token_lifespan": "15s",
    }
    try:
        fixture.start()
        fixture.operator(
            "enrollment-approve",
            "--issuer",
            fixture.env["C1_ISSUER"],
            "--subject",
            "external|approved",
            "--operator",
            "synthetic-operator",
        )
        origin = fixture.env["C1_EXPLORER_ORIGIN"]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            login(page, origin)
            page.get_by_role("button", name="Confirm enrollment", exact=True).click()
            page.wait_for_url(origin + "/explorer/")
            cookies = page.context.cookies()
            session = next(c for c in cookies if c["name"] == "__Host-c1_session")
            assert session["secure"] and session["httpOnly"] and session["path"] == "/"
            assert session["sameSite"] == "Strict"
            assert all("token" not in c["name"] for c in cookies)
            response = page.goto(origin + "/explorer/scopes")
            assert response is not None and response.status == 200
            assert response.headers["content-security-policy"]
            assert response.headers["x-content-type-options"] == "nosniff"
            # Cross-origin/CSRF attempts do not terminate the local session.
            denied = page.request.post(origin + "/explorer/logout", form={"csrf": "wrong"})
            assert denied.status == 403
            page.goto(origin + "/explorer/signed-out")
            page.wait_for_url(origin + "/explorer/")
            time.sleep(16)
            page.goto(origin + "/explorer/scopes")
            if refresh:
                page.wait_for_url(origin + "/explorer/scopes")
                assert "External login" not in page.content()
                page.get_by_role("button", name="Sign out", exact=True).click()
                assert "Signed out" in page.content()
                assert not any(c["name"] == "__Host-c1_session" for c in page.context.cookies())
            else:
                page.get_by_label("User", exact=True).wait_for()
                assert not any(c["name"] == "__Host-c1_session" for c in page.context.cookies())
            browser.close()
    finally:
        fixture.close()


def test_t05_provider_logout_and_independent_api_token(external: External) -> None:
    external.stop_server()
    external.env["C1_EXPLORER_LOGOUT_MODE"] = "rp-initiated"
    assert external.ui is not None
    external.ui.remember_login = True
    external.start_server()
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    origin = external.env["C1_EXPLORER_ORIGIN"]
    tokens = external.user_tokens("approved")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(90000)
        login(page, origin)
        page.get_by_role("button", name="Confirm enrollment", exact=True).click()
        page.wait_for_url(origin + "/explorer/")
        page.goto(origin + "/explorer/scopes")
        with page.expect_response(lambda r: r.url.endswith("/explorer/logout")) as logout:
            page.get_by_role("button", name="Sign out", exact=True).click()
        assert logout.value.status == 200
        assert "Signed out" in page.content()
        page.get_by_role("link", name="Sign out of identity provider", exact=True).click()
        try:
            page.wait_for_url(origin + "/explorer/signed-out", timeout=10000)
        except Exception:
            import re
            from urllib.parse import urlsplit

            body = re.sub(r"[\w-]+\.[\w-]+\.[\w-]+", "[redacted]", page.inner_text("body"))
            raise AssertionError(urlsplit(page.url).path + " " + body[:700]) from None
        assert "Signed out" in page.content()
        assert not any(c["name"] == "__Host-c1_session" for c in page.context.cookies())
        browser.close()
    # Logout does not promise to revoke independently issued bearer tokens.
    with httpx.Client(trust_env=False) as client:
        assert (
            client.get(
                origin + "/v1/whoami",
                headers={"Authorization": "Bearer " + tokens["access_token"]},
            ).status_code
            == 200
        )


def test_t05_real_session_maximum_lifetime(external: External) -> None:
    external.stop_server()
    external.env.update(C1_EXPLORER_SESSION_IDLE_S="60", C1_EXPLORER_SESSION_MAX_S="60")
    external.start_server()
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    origin = external.env["C1_EXPLORER_ORIGIN"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        login(page, origin)
        page.get_by_role("button", name="Confirm enrollment", exact=True).click()
        page.wait_for_url(origin + "/explorer/")
        page.goto(origin + "/explorer/scopes")
        time.sleep(61)
        page.goto(origin + "/explorer/scopes")
        page.get_by_label("User", exact=True).wait_for()
        browser.close()
