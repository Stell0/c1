"""Supervisor-owned identity UI for the pinned, real Ory Hydra test provider.

Hydra delegates authentication/consent to a login service by design. This
synthetic fixture authenticates two test accounts; C1 never calls its admin API.
It is not an OIDC mock: Hydra issues, signs, exchanges and refreshes the tokens.
"""

from __future__ import annotations

import secrets
import threading
import time
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx


class HydraIdentityUI:
    def __init__(self, admin: str, port: int = 29092) -> None:
        self.admin = admin
        self.transactions: dict[str, tuple[str, float]] = {}
        self.remember_login = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def respond(
                self, status: int, body: str = "", location: str = "", cookie: str = ""
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                if location:
                    self.send_header("Location", location)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_GET(self) -> None:
                params = parse_qs(urlsplit(self.path).query)
                if self.path.startswith("/login?") and "login_challenge" in params:
                    challenge = params["login_challenge"][0]
                    nonce = secrets.token_urlsafe(24)
                    owner.transactions[nonce] = (challenge, time.monotonic() + 300)
                    body = (
                        "<!doctype html><html><title>Hydra test login</title>"
                        "<h1>External login</h1>"
                        '<form method="post" action="/login">'
                        f'<input name="csrf" type="hidden" value="{escape(nonce)}">'
                        '<label>User<input name="username"></label>'
                        '<label>Password<input type="password" name="password"></label>'
                        '<button type="submit">Sign in</button></form></html>'
                    )
                    self.respond(200, body, cookie=f"hydra_login={nonce}; HttpOnly; SameSite=Lax")
                elif self.path.startswith("/consent?") and "consent_challenge" in params:
                    challenge = params["consent_challenge"][0]
                    with httpx.Client(trust_env=False, timeout=10) as client:
                        request = client.get(
                            owner.admin + "/admin/oauth2/auth/requests/consent",
                            params={"consent_challenge": challenge},
                        )
                        request.raise_for_status()
                        body = request.json()
                        accepted = client.put(
                            owner.admin + "/admin/oauth2/auth/requests/consent/accept",
                            params={"consent_challenge": challenge},
                            json={
                                "grant_scope": body["requested_scope"],
                                "grant_access_token_audience": body[
                                    "requested_access_token_audience"
                                ],
                                "session": {
                                    "access_token": {
                                        "c1_principal_kind": "human",
                                        "token_use": "access",
                                        "provider_admin": body["subject"] == "external|other",
                                    },
                                    "id_token": {},
                                },
                                "remember": False,
                            },
                        )
                        accepted.raise_for_status()
                        self.respond(302, location=accepted.json()["redirect_to"])
                elif self.path.startswith("/logout?") and "logout_challenge" in params:
                    with httpx.Client(trust_env=False, timeout=10) as client:
                        response = client.put(
                            owner.admin + "/admin/oauth2/auth/requests/logout/accept",
                            params={"logout_challenge": params["logout_challenge"][0]},
                        )
                        response.raise_for_status()
                        self.respond(302, location=response.json()["redirect_to"])
                else:
                    self.respond(404)

            def do_POST(self) -> None:
                if self.path != "/login":
                    self.respond(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 8192:
                    self.respond(400)
                    return
                values = parse_qs(self.rfile.read(length).decode())
                nonce = values.get("csrf", [""])[0]
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                transaction = owner.transactions.pop(nonce, None)
                name = values.get("username", [""])[0]
                if (
                    transaction is None
                    or transaction[1] <= time.monotonic()
                    or "hydra_login" not in cookie
                    or cookie["hydra_login"].value != nonce
                    or name not in {"approved", "other"}
                    or values.get("password") != ["synthetic-test-password"]
                ):
                    self.respond(403)
                    return
                with httpx.Client(trust_env=False, timeout=10) as client:
                    response = client.put(
                        owner.admin + "/admin/oauth2/auth/requests/login/accept",
                        params={"login_challenge": transaction[0]},
                        json={"subject": "external|" + name, "remember": owner.remember_login},
                    )
                    response.raise_for_status()
                    self.respond(302, location=response.json()["redirect_to"])

            def log_message(self, format: str, *args: Any) -> None:
                # OAuth codes/challenges never enter public test evidence.
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
