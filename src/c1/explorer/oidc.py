"""Authorization code + PKCE against the configured issuer (M12 D2).

The Explorer is a confidential client. It exchanges codes server-side,
validates the ID token only to finish login, and keeps the access and
refresh tokens in the server-side session. The ID token is never sent to
the C1 API; the API validates the access token as for any other client.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt import PyJWKSet

from c1.config import ExplorerSettings
from c1.explorer.sessions import LoginTransaction, Tokens

_ALGORITHMS = ["RS256", "ES256"]


class LoginError(Exception):
    """A safe sign-in failure; it never carries token or code text."""


@dataclass(frozen=True)
class Endpoints:
    authorization: str
    token: str
    end_session: str
    jwks: str


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _same_origin(url: str, issuer: str) -> bool:
    left, right = urlsplit(url), urlsplit(issuer)
    return (
        left.scheme == right.scheme
        and left.hostname == right.hostname
        and left.port == right.port
        and left.path.startswith(right.path.rstrip("/") + "/")
        and left.username is None
        and not left.query
        and not left.fragment
    )


class OIDCClient:
    def __init__(self, issuer: str, settings: ExplorerSettings, *, timeout_s: float) -> None:
        self.issuer, self.settings = issuer, settings
        self._http = httpx.AsyncClient(timeout=timeout_s, trust_env=False, follow_redirects=False)
        self._endpoints: Endpoints | None = None
        self._jwks: tuple[float, PyJWKSet] | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    async def endpoints(self) -> Endpoints:
        if self._endpoints is not None:
            return self._endpoints
        async with self._lock:
            if self._endpoints is None:
                url = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
                try:
                    response = await self._http.get(url)
                    response.raise_for_status()
                    document = response.json()
                except (httpx.HTTPError, ValueError):
                    raise LoginError("identity_unavailable") from None
                if not isinstance(document, dict) or document.get("issuer") != self.issuer:
                    raise LoginError("untrusted_discovery")
                values = {
                    key: document.get(key)
                    for key in (
                        "authorization_endpoint",
                        "token_endpoint",
                        "end_session_endpoint",
                        "jwks_uri",
                    )
                }
                if not all(
                    isinstance(v, str) and _same_origin(v, self.issuer) for v in values.values()
                ):
                    raise LoginError("untrusted_discovery")
                self._endpoints = Endpoints(
                    authorization=str(values["authorization_endpoint"]),
                    token=str(values["token_endpoint"]),
                    end_session=str(values["end_session_endpoint"]),
                    jwks=str(values["jwks_uri"]),
                )
        assert self._endpoints is not None
        return self._endpoints

    async def authorization_url(self, login: LoginTransaction) -> str:
        endpoints = await self.endpoints()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "scope": "openid",
                "state": login.state,
                "nonce": login.nonce,
                "code_challenge": code_challenge(login.verifier),
                "code_challenge_method": "S256",
            }
        )
        return endpoints.authorization + "?" + query

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        endpoints = await self.endpoints()
        try:
            response = await self._http.post(
                endpoints.token,
                data=form,
                auth=(self.settings.client_id, self.settings.client_secret),
            )
        except httpx.HTTPError:
            raise LoginError("identity_unavailable") from None
        if response.status_code != 200:
            raise LoginError("token_rejected")
        try:
            body = response.json()
        except ValueError:
            raise LoginError("token_rejected") from None
        if not isinstance(body, dict) or body.get("token_type", "").lower() != "bearer":
            raise LoginError("token_rejected")
        return body

    @staticmethod
    def _tokens(body: dict[str, Any], now: float) -> Tokens:
        access = body.get("access_token")
        expires = body.get("expires_in")
        if not isinstance(access, str) or not access or type(expires) is not int:
            raise LoginError("token_rejected")
        refresh = body.get("refresh_token")
        refresh_expires = body.get("refresh_expires_in")
        return Tokens(
            access_token=access,
            access_expires_at=now + expires,
            refresh_token=refresh if isinstance(refresh, str) and refresh else None,
            refresh_expires_at=(
                now + refresh_expires
                if type(refresh_expires) is int and refresh_expires > 0
                else None
            ),
        )

    async def exchange(self, code: str, login: LoginTransaction) -> tuple[Tokens, dict[str, Any]]:
        if not code or len(code) > 4096:
            raise LoginError("invalid_code")
        now = time.monotonic()
        body = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "code_verifier": login.verifier,
            }
        )
        claims = await self._id_claims(body.get("id_token"), login.nonce)
        return self._tokens(body, now), claims

    async def refresh(self, tokens: Tokens) -> Tokens:
        if tokens.refresh_token is None:
            raise LoginError("no_refresh")
        now = time.monotonic()
        body = await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
        )
        return self._tokens(body, now)

    async def logout(self, tokens: Tokens) -> None:
        """End the identity-provider session server-side; failure still ends ours."""
        if tokens.refresh_token is None:
            return
        try:
            endpoints = await self.endpoints()
            await self._http.post(
                endpoints.end_session,
                data={"refresh_token": tokens.refresh_token},
                auth=(self.settings.client_id, self.settings.client_secret),
            )
        except (httpx.HTTPError, LoginError):
            return

    async def _id_claims(self, id_token: object, nonce: str) -> dict[str, Any]:
        if not isinstance(id_token, str) or not id_token or len(id_token) > 16384:
            raise LoginError("missing_id_token")
        try:
            header = jwt.get_unverified_header(id_token)
            kid = header.get("kid")
            if (
                header.get("alg") not in _ALGORITHMS
                or not isinstance(kid, str)
                or any(name in header for name in ("jku", "x5u", "jwk"))
            ):
                raise LoginError("invalid_id_token")
            key = (await self._key_set(refresh=False))[kid] if await self._has(kid) else None
            if key is None:
                key = (await self._key_set(refresh=True))[kid]
            claims = jwt.decode(
                id_token,
                key.key,
                algorithms=_ALGORITHMS,
                audience=self.settings.client_id,
                issuer=self.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
            )
        except LoginError:
            raise
        except (jwt.PyJWTError, ValueError, KeyError, httpx.HTTPError):
            raise LoginError("invalid_id_token") from None
        if claims.get("typ") not in (None, "ID") or claims.get("nonce") != nonce:
            raise LoginError("invalid_id_token")
        return dict(claims)

    async def _key_set(self, *, refresh: bool) -> PyJWKSet:
        now = time.monotonic()
        if self._jwks is not None and not refresh and now - self._jwks[0] < 300:
            return self._jwks[1]
        endpoints = await self.endpoints()
        response = await self._http.get(endpoints.jwks)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise LoginError("invalid_id_token")
        key_set = PyJWKSet.from_dict(data)
        self._jwks = (now, key_set)
        return key_set

    async def _has(self, kid: str) -> bool:
        try:
            (await self._key_set(refresh=False))[kid]
        except KeyError:
            return False
        return True
