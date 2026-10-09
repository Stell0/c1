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
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlencode

import httpx
import jwt
from jwt import PyJWKSet

from c1.config import ExplorerSettings
from c1.explorer.sessions import LoginTransaction, Tokens
from c1.oidc import trusted_endpoint

_ALGORITHMS = ["RS256", "ES256"]


class LoginError(Exception):
    """A safe sign-in failure; it never carries token or code text."""


@dataclass(frozen=True)
class Endpoints:
    authorization: str
    token: str
    end_session: str | None
    jwks: str


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OIDCClient:
    def __init__(
        self,
        issuer: str,
        settings: ExplorerSettings,
        *,
        timeout_s: float,
        verify: ssl.SSLContext | bool = True,
        allowed_endpoints: tuple[str, ...] = (),
        api_audience: str = "",
    ) -> None:
        self.issuer, self.settings = issuer, settings
        self.allowed_endpoints = allowed_endpoints
        self.api_audience = api_audience
        self._http = httpx.AsyncClient(
            timeout=timeout_s, trust_env=False, follow_redirects=False, verify=verify
        )
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
                for field, required in (
                    ("response_types_supported", "code"),
                    ("token_endpoint_auth_methods_supported", "client_secret_basic"),
                    ("code_challenge_methods_supported", "S256"),
                ):
                    advertised = document.get(field)
                    if advertised is not None and (
                        not isinstance(advertised, list)
                        or not all(isinstance(value, str) for value in advertised)
                        or required not in advertised
                    ):
                        raise LoginError("unsupported_" + field)
                signing = document.get("id_token_signing_alg_values_supported")
                if signing is not None and (
                    not isinstance(signing, list)
                    or not all(isinstance(value, str) for value in signing)
                    or not any(value in _ALGORITHMS for value in signing)
                ):
                    raise LoginError("unsupported_id_token_signing_algorithm")
                values = {
                    key: document.get(key)
                    for key in (
                        "authorization_endpoint",
                        "token_endpoint",
                        "jwks_uri",
                    )
                }
                if not all(
                    trusted_endpoint(v, self.issuer, self.allowed_endpoints)
                    for v in values.values()
                ):
                    raise LoginError("untrusted_discovery")
                end_session = document.get("end_session_endpoint")
                if end_session is not None and not trusted_endpoint(
                    end_session, self.issuer, self.allowed_endpoints
                ):
                    raise LoginError("untrusted_discovery")
                self._endpoints = Endpoints(
                    authorization=str(values["authorization_endpoint"]),
                    token=str(values["token_endpoint"]),
                    end_session=end_session,
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
                "scope": self.settings.scopes,
                "state": login.state,
                "nonce": login.nonce,
                "code_challenge": code_challenge(login.verifier),
                "code_challenge_method": "S256",
                **(
                    {self.settings.audience_parameter: self.api_audience}
                    if self.settings.audience_parameter != "none"
                    else {}
                ),
            }
        )
        return endpoints.authorization + "?" + query

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        endpoints = await self.endpoints()
        try:
            response = await self._http.post(
                endpoints.token,
                data=form,
                auth=self._client_auth(),
            )
        except httpx.HTTPError:
            raise LoginError("identity_unavailable") from None
        if response.status_code != 200:
            raise LoginError("token_rejected")
        try:
            body = response.json()
        except ValueError:
            raise LoginError("token_rejected") from None
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("token_type"), str)
            or body["token_type"].lower() != "bearer"
        ):
            raise LoginError("token_rejected")
        return body

    def _client_auth(self) -> httpx.BasicAuth:
        # OAuth client_secret_basic encodes each credential as form data before
        # applying HTTP Basic (RFC 6749 2.3.1), including reserved characters.
        return httpx.BasicAuth(
            quote_plus(self.settings.client_id, safe=""),
            quote_plus(self.settings.client_secret, safe=""),
        )

    @staticmethod
    def _tokens(body: dict[str, Any], now: float) -> Tokens:
        access = body.get("access_token")
        expires = body.get("expires_in")
        if not isinstance(access, str) or not access or type(expires) is not int or expires <= 0:
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
        tokens = self._tokens(body, now)
        tokens.identity_token = str(body["id_token"])
        return tokens, claims

    async def refresh(self, tokens: Tokens) -> Tokens:
        if tokens.refresh_token is None or (
            tokens.refresh_expires_at is not None and tokens.refresh_expires_at <= time.monotonic()
        ):
            raise LoginError("no_refresh")
        now = time.monotonic()
        body = await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
        )
        refreshed = self._tokens(body, now)
        if "refresh_token" not in body:
            refreshed.refresh_token = tokens.refresh_token
            refreshed.refresh_expires_at = tokens.refresh_expires_at
        # Keep the original validated ID token as the RP logout hint; a refresh
        # response's ID token is not used without its own complete validation.
        refreshed.identity_token = tokens.identity_token
        return refreshed

    async def logout(self, tokens: Tokens) -> str | None:
        """Return a trusted RP target or perform supported backchannel logout."""
        if self.settings.logout_mode == "local":
            return None
        try:
            endpoints = await self.endpoints()
            if endpoints.end_session is None:
                return None
            if self.settings.logout_mode == "rp-initiated":
                if tokens.identity_token is None:
                    return None
                return (
                    endpoints.end_session
                    + "?"
                    + urlencode(
                        {
                            "id_token_hint": tokens.identity_token,
                            "client_id": self.settings.client_id,
                            "post_logout_redirect_uri": self.settings.origin
                            + "/explorer/signed-out",
                        }
                    )
                )
            if tokens.refresh_token is None:
                return None
            await self._http.post(
                endpoints.end_session,
                data={"refresh_token": tokens.refresh_token},
                auth=self._client_auth(),
            )
        except (httpx.HTTPError, LoginError):
            return None
        return None

    async def _id_claims(self, id_token: object, nonce: str) -> dict[str, Any]:
        if not isinstance(id_token, str) or not id_token or len(id_token) > 16384:
            raise LoginError("missing_id_token")
        try:
            header = jwt.get_unverified_header(id_token)
            kid = header.get("kid")
            if (
                header.get("alg") not in _ALGORITHMS
                or header.get("typ") not in (None, "JWT", "application/jwt")
                or not isinstance(kid, str)
                or any(name in header for name in ("jku", "x5u", "jwk"))
            ):
                raise LoginError("invalid_id_token")
            key = (await self._key_set(refresh=False))[kid] if await self._has(kid) else None
            if key is None:
                key = (await self._key_set(refresh=True))[kid]
            if (
                key.algorithm_name != header["alg"]
                or key.key_type != ("RSA" if header["alg"] == "RS256" else "EC")
                or key.public_key_use not in (None, "sig")
            ):
                raise LoginError("invalid_id_token")
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
        audience = claims.get("aud")
        if (
            not isinstance(claims.get("sub"), str)
            or not claims["sub"]
            or any(type(claims.get(name)) not in (int, float) for name in ("exp", "iat"))
            or claims["exp"] <= claims["iat"]
            or ("azp" in claims and claims["azp"] != self.settings.client_id)
            or (
                isinstance(audience, list)
                and len(audience) > 1
                and claims.get("azp") != self.settings.client_id
            )
        ):
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
