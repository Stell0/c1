"""M12 Explorer unit checks: login, sessions, CSRF/origin, forms, escaping, boundaries."""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from c1.config import ExplorerSettings, Settings
from c1.explorer.app import _safe_return, create_explorer
from c1.explorer.client import ApiClient
from c1.explorer.oidc import LoginError, code_challenge
from c1.explorer.render import Renderer
from c1.explorer.security import CSP, FormError, parse_form, single
from c1.explorer.sessions import LOGIN_TTL_S, SessionStore, Tokens

ROOT = Path(__file__).resolve().parents[3]
EXPLORER = ROOT / "src/c1/explorer"
ORIGIN = "http://127.0.0.1:18095"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        instance_id="c1test",
        instance_base="urn:c1:instance:test:",
        issuer="http://127.0.0.1:18090/realms/test",
        issuer_alias="dev",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token="test-secret",  # pragma: allowlist secret - local fake credential
        fga_store="test-store",
        fga_model="test-model",
        terminus_url="http://127.0.0.1:16363",
        terminus_password="test-secret",  # pragma: allowlist secret - local fake credential
        organization="admin",
        knowledge_database="knowledge_test",
        workflow_database="workflow_test",
        lock_path=tmp_path / "lock",
    )


def _explorer_settings() -> ExplorerSettings:
    return ExplorerSettings(
        origin=ORIGIN,
        client_id="c1-explorer",
        client_secret="synthetic-client-credential",  # pragma: allowlist secret - fake
    )


def _api(calls: list[tuple[str, str, str]]) -> Any:
    """A stand-in /v1 API that records the bearer token of every call."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            calls.append(
                (scope["method"], scope["path"], headers.get(b"authorization", b"").decode())
            )
            body: bytes = b"{}"
            if scope["path"] == "/v1/instance":
                body = b'{"instance_id":"c1test","instance_base":"urn:c1:instance:test:",'
                body += b'"knowledge_revision":"branch:abc"}'
            elif scope["path"] == "/v1/whoami":
                body = b'{"issuer_alias":"dev","subject":"s","kind":"human"}'
            elif scope["path"] == "/v1/setup/identity":
                body = b'{"subject":"s","kind":"human","enrollment_pending":false}'
            elif scope["path"] == "/v1/changesets/cs-1/withdraw":
                body = b'{"id":"cs-1","state":"withdrawn"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})

    return app


class _FakeOIDC:
    def __init__(self) -> None:
        self.refresh_fails = False
        self.exchanged: list[str] = []

    async def authorization_url(self, login: Any) -> str:
        return (
            "http://127.0.0.1:18090/realms/test/auth?state="
            + str(login.state)
            + "&code_challenge="
            + code_challenge(login.verifier)
            + "&code_challenge_method=S256"
        )

    async def exchange(self, code: str, login: Any) -> tuple[Tokens, dict[str, Any]]:
        self.exchanged.append(code)
        return Tokens("access-1", 10**9), {"sub": "s", "preferred_username": "carol"}

    async def refresh(self, tokens: Tokens) -> Tokens:
        if self.refresh_fails:
            raise LoginError("token_rejected")
        return Tokens("access-2", 10**9)

    async def logout(self, tokens: Tokens) -> None:
        return None

    async def close(self) -> None:
        return None


def _client(tmp_path: Path) -> tuple[Any, list[tuple[str, str, str]], _FakeOIDC, Any]:
    calls: list[tuple[str, str, str]] = []
    app = create_explorer(_settings(tmp_path), _explorer_settings(), _api(calls))
    oidc = _FakeOIDC()
    explorer = app.state.explorer
    explorer.oidc = oidc
    # httpx sends Secure cookies only over https; browsers also accept them on loopback http.
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://127.0.0.1:18095"
    )
    return client, calls, oidc, explorer


async def _signed_in(client: httpx.AsyncClient) -> str:
    login = await client.get("/explorer/login")
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    callback = await client.get("/explorer/callback", params={"state": state, "code": "c-1"})
    assert callback.status_code == 200
    page = await client.get("/explorer/")
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match
    return match.group(1)


def test_login_cookies_pkce_and_state(tmp_path: Path) -> None:
    async def run() -> None:
        client, calls, oidc, explorer = _client(tmp_path)
        async with client:
            anonymous = await client.get("/explorer/entities?label=x")
            assert anonymous.status_code == 303
            assert anonymous.headers["location"].startswith("/explorer/login?next=")
            assert calls == []
            login = await client.get("/explorer/login")
            assert login.status_code == 303
            cookie = login.headers["set-cookie"]
            assert cookie.startswith("__Host-c1_login=")
            for attribute in ("HttpOnly", "Path=/", "SameSite=lax", "Secure"):
                assert attribute.lower() in cookie.lower()
            query = parse_qs(urlsplit(login.headers["location"]).query)
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            wrong = await client.get("/explorer/callback", params={"state": "x", "code": "c"})
            assert wrong.status_code == 400 and len(explorer.sessions) == 0
            # The failed attempt consumed the transaction; the right state is now unknown.
            again = await client.get("/explorer/callback", params={"state": state, "code": "c"})
            assert again.status_code == 400 and oidc.exchanged == []

            csrf = await _signed_in(client)
            assert len(explorer.sessions) == 1 and csrf
            session_cookie = [c for c in client.cookies.jar if c.name == "__Host-c1_session"]
            assert session_cookie and session_cookie[0].secure
            page = await client.get("/explorer/")
            assert page.status_code == 200
            assert page.headers["content-security-policy"] == CSP
            assert page.headers["cache-control"] == "no-store"
            assert page.headers["referrer-policy"] == "same-origin"
            assert "<script" not in page.text
            assert all(token == "Bearer access-1" for _m, _p, token in calls)
            assert all(path.startswith("/v1/") for _m, path, _t in calls)

    asyncio.run(run())


def test_callback_sets_strict_session_cookie_and_same_site_continuation(tmp_path: Path) -> None:
    async def run() -> None:
        client, _calls, _oidc, _explorer = _client(tmp_path)
        async with client:
            login = await client.get("/explorer/login?next=/explorer/documents")
            state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
            callback = await client.get("/explorer/callback", params={"state": state, "code": "c"})
            cookies = callback.headers.get_list("set-cookie")
            session = next(c for c in cookies if c.startswith("__Host-c1_session="))
            assert "samesite=strict" in session.lower() and "httponly" in session.lower()
            assert any(c.startswith("__Host-c1_login=") and "Max-Age=0" in c for c in cookies)
            assert "url=/explorer/documents" in callback.text
            assert callback.status_code == 200

    asyncio.run(run())


def test_post_requires_origin_session_and_csrf_before_any_api_call(tmp_path: Path) -> None:
    async def run() -> None:
        client, calls, _oidc, _explorer = _client(tmp_path)
        async with client:
            csrf = await _signed_in(client)
            calls.clear()
            path = "/explorer/changeset/action"
            form = {"csrf": csrf, "id": "cs-1", "action": "withdraw"}
            no_origin = await client.post(path, data=form)
            foreign = await client.post(path, data=form, headers={"Origin": "http://evil"})
            missing = await client.post(
                path, data={"id": "cs-1", "action": "withdraw"}, headers={"Origin": ORIGIN}
            )
            wrong = await client.post(
                path, data={**form, "csrf": "nope"}, headers={"Origin": ORIGIN}
            )
            duplicate = await client.post(
                path,
                content=f"csrf={csrf}&csrf={csrf}&id=cs-1&action=withdraw",
                headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
            )
            multipart = await client.post(
                path, files={"csrf": ("a", b"b")}, headers={"Origin": ORIGIN}
            )
            assert [r.status_code for r in (no_origin, foreign, missing, wrong, duplicate)] == [
                403
            ] * 5
            assert multipart.status_code == 400
            assert calls == []
            ok = await client.post(path, data=form, headers={"Origin": ORIGIN})
            assert ok.status_code == 303
            assert ("POST", "/v1/changesets/cs-1/withdraw", "Bearer access-1") in calls
            bad_action = await client.post(
                path, data={**form, "action": "delete"}, headers={"Origin": ORIGIN}
            )
            assert bad_action.status_code == 400

    asyncio.run(run())


def test_refresh_failure_and_logout_end_the_session(tmp_path: Path) -> None:
    async def run() -> None:
        client, _calls, oidc, explorer = _client(tmp_path)
        async with client:
            csrf = await _signed_in(client)
            [session] = list(explorer.sessions._sessions.values())
            session.tokens.access_expires_at = 0
            oidc.refresh_fails = True
            page = await client.get("/explorer/")
            assert page.status_code == 303 and len(explorer.sessions) == 0
            csrf = await _signed_in(client)
            out = await client.post(
                "/explorer/logout", data={"csrf": csrf}, headers={"Origin": ORIGIN}
            )
            assert out.status_code == 200 and len(explorer.sessions) == 0
            assert (await client.get("/explorer/")).status_code == 303

    asyncio.run(run())


def test_unknown_paths_and_methods_keep_security_headers(tmp_path: Path) -> None:
    async def run() -> None:
        client, calls, _oidc, _explorer = _client(tmp_path)
        async with client:
            for response in (
                await client.get("/explorer/nowhere"),
                await client.delete("/explorer/entities"),
                await client.get("/explorer/static/../app.py"),
            ):
                assert response.status_code in {404, 405}
                assert response.headers["content-security-policy"] == CSP
            assert calls == []

    asyncio.run(run())


def test_session_store_expiry_and_single_use_login() -> None:
    now = [0.0]
    store = SessionStore(idle_s=60, max_s=120, clock=lambda: now[0])
    session_id = store.create(Tokens("t", 10.0))
    now[0] = 59
    assert store.get(session_id) is not None
    now[0] = 118
    assert store.get(session_id) is not None
    now[0] = 121
    assert store.get(session_id) is None
    other = store.create(Tokens("t", 10.0))
    now[0] = 121 + 61
    assert store.get(other) is None
    handle, login = store.begin_login("/explorer/")
    assert store.finish_login(handle, login.state) is login
    assert store.finish_login(handle, login.state) is None
    handle, login = store.begin_login("/explorer/")
    now[0] += LOGIN_TTL_S + 1
    assert store.finish_login(handle, login.state) is None
    assert store.get(None) is None and store.get("x" * 200) is None


def test_safe_return_only_allows_explorer_paths() -> None:
    assert _safe_return("/explorer/entities?label=a") == "/explorer/entities?label=a"
    for value in (
        "http://evil/explorer/",
        "//evil/explorer/",
        "/v1/instance",
        "/explorer\\x",
        "https:/explorer/",
        "/explorer",
    ):
        assert _safe_return(value) == "/explorer/"


def test_form_parsing_limits() -> None:
    form = "application/x-www-form-urlencoded"
    assert parse_form(b"a=1&b=x%0Ay", form) == {"a": ["1"], "b": ["x\ny"]}
    with pytest.raises(FormError):
        parse_form(b"a=1", "multipart/form-data")
    with pytest.raises(FormError):
        parse_form(b"a=" + b"x" * (64 * 1024), form)
    with pytest.raises(FormError):
        parse_form(b"a=%00", form)
    with pytest.raises(FormError):
        parse_form(b"a=%ff", form)
    with pytest.raises(FormError):
        single({"a": ["1", "2"]}, "a")
    with pytest.raises(FormError):
        single({}, "a")
    assert single({}, "a", required=False) == ""


def test_pkce_challenge_matches_rfc7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # pragma: allowlist secret
    assert code_challenge(verifier) == expected


def test_widgets_escape_hostile_values() -> None:
    renderer = Renderer(instance_base_hint="urn:c1:instance:test:")
    hostile = "<script>alert(1)</script>\"'><img src=x onerror=alert(2)>"
    template = renderer.env.from_string(
        '{% import "widgets.html" as w %}'
        "{{ w.record(r) }}{{ w.data(d) }}{{ w.text_block(t) }}{{ w.locator(t) }}{{ w.iri(i) }}"
    )
    html = template.render(
        r={
            "id": "urn:c1:instance:test:entity/1",
            "types": ["urn:c1:ns:core#Entity"],
            "properties": {
                "http://www.w3.org/2004/02/skos/core#prefLabel": [
                    {"lexical": hostile, "datatype": "http://www.w3.org/2001/XMLSchema#string"}
                ],
                "http://purl.org/dc/terms/identifier": [
                    {"lexical": "javascript:alert(3)", "datatype": "x"}
                ],
            },
        },
        d={"k": [hostile, {"nested": hostile}]},
        t=hostile,
        i="javascript:alert(4)",
    )
    assert (
        "<script" not in html
        and "<img" not in html
        and "onerror=alert" not in html.replace("onerror=alert(2)&gt;", "")
    )
    assert "&lt;script&gt;" in html
    assert 'href="javascript' not in html
    assert renderer.resource_href("javascript:alert(1)") is None
    assert renderer.resource_href("urn:c1:instance:test:entity/1") == (
        "/explorer/resource?id=urn%3Ac1%3Ainstance%3Atest%3Aentity%2F1"
    )


def test_templates_and_code_never_mark_data_safe() -> None:
    for path in EXPLORER.rglob("*"):
        if path.suffix not in {".html", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "|safe" not in text.replace(" ", "") and "Markup(" not in text, path
        assert "autoescape false" not in text and "autoescape=False" not in text, path
        assert "<script" not in text, path


def test_explorer_imports_no_privileged_c1_module() -> None:
    allowed = ("c1.config", "c1.model", "c1.explorer", "c1.oidc")
    for path in EXPLORER.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name == "c1" or name.startswith("c1."):
                    assert name.startswith(allowed), (path.name, name)


def test_api_client_only_calls_the_public_api() -> None:
    client = ApiClient(FastAPI())

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.call("t", "GET", "/explorer/")
        await client.close()

    asyncio.run(run())


def test_explorer_settings_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "synthetic-client-credential"  # pragma: allowlist secret - fake
    for origin in ("http://explorer.example", "https://x.example/explorer", "ftp://x"):
        with pytest.raises(ValueError):
            ExplorerSettings(origin=origin, client_id="c1-explorer", client_secret=secret)
    with pytest.raises(ValueError):
        ExplorerSettings(origin=ORIGIN, client_id="c1-explorer", client_secret="short")
    with pytest.raises(ValueError):
        ExplorerSettings(
            origin=ORIGIN, client_id="c1-explorer", client_secret=secret, session_idle_s=10
        )
    assert ExplorerSettings(
        origin="https://c1.example", client_id="c1-explorer", client_secret=secret
    ).secure_transport
    monkeypatch.delenv("C1_EXPLORER_ENABLED", raising=False)
    assert ExplorerSettings.from_env() is None
    monkeypatch.setenv("C1_EXPLORER_ENABLED", "true")
    monkeypatch.delenv("C1_EXPLORER_ORIGIN", raising=False)
    with pytest.raises(ValueError):
        ExplorerSettings.from_env()
    assert (
        repr(ExplorerSettings(origin=ORIGIN, client_id="c", client_secret=secret)).count(secret)
        == 0
    )
