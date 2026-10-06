"""Validate only access tokens from the configured OIDC issuer."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWKClient

from c1 import roundtrips
from c1.authorization.principal import Principal
from c1.config import Settings

_ALGORITHMS = ("RS256", "ES256")
_MAX_TOKEN_BYTES = 16_384
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]


class AuthenticationError(ValueError):
    """Safe authentication failure; its message never includes token bytes."""

    def __init__(self, reason: str = "invalid_token") -> None:
        self.reason = reason
        super().__init__("Invalid bearer token")


class _TrustedJWKClient(PyJWKClient):
    """PyJWT key selection with a bounded, no-proxy fetch of the trusted URL."""

    verify: ssl.SSLContext | bool = True

    def fetch_data(self) -> dict[str, Any]:
        with httpx.Client(
            timeout=self.timeout, trust_env=False, follow_redirects=False, verify=self.verify
        ) as client:
            response = client.get(self.uri)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("JWKS must be an object")
        return data


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname or "", parsed.port


class TokenValidator:
    """Only signed bearer tokens can produce a principal.

    JWKS keys may be cached for 300 seconds. No authorization decision or
    token payload is cached. A fresh discovery and JWKS fetch gate readiness.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._verify = settings.issuer_verify()
        self._http = httpx.AsyncClient(
            timeout=settings.backend_timeout_s,
            trust_env=False,
            follow_redirects=False,
            verify=self._verify,
        )
        self._client: _TrustedJWKClient | None = None
        self._jwks_uri: str | None = None
        self._discovery_lock = asyncio.Lock()

    async def _discover(self) -> str:
        url = self.settings.issuer.rstrip("/") + "/.well-known/openid-configuration"
        response = await self._http.get(url)
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict) or document.get("issuer") != self.settings.issuer:
            raise AuthenticationError("untrusted_discovery")
        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise AuthenticationError("untrusted_discovery")
        parsed = urlsplit(jwks_uri)
        issuer_path = urlsplit(self.settings.issuer).path.rstrip("/") + "/"
        if (
            parsed.scheme not in {"http", "https"}
            or _origin(jwks_uri) != _origin(self.settings.issuer)
            or not parsed.path.startswith(issuer_path)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AuthenticationError("untrusted_discovery")
        return jwks_uri

    async def _ensure_client(self) -> _TrustedJWKClient:
        if self._client is not None:
            return self._client
        async with self._discovery_lock:
            if self._client is None:
                uri = await self._discover()
                self._client = _TrustedJWKClient(
                    uri,
                    cache_jwk_set=True,
                    cache_keys=False,
                    lifespan=300,
                    timeout=int(self.settings.backend_timeout_s),
                    cooldown_duration=0,
                )
                self._client.verify = self._verify
                self._jwks_uri = uri
        assert self._client is not None
        return self._client

    @roundtrips.phased("auth.token")
    async def authenticate(self, token: str) -> Principal:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > _MAX_TOKEN_BYTES
            or token.count(".") != 2
            or any(char.isspace() for char in token)
        ):
            raise AuthenticationError()
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if (
                algorithm not in _ALGORITHMS
                or not isinstance(key_id, str)
                or not key_id
                or len(key_id) > 256
                or any(name in header for name in ("jku", "x5u", "jwk"))
            ):
                raise AuthenticationError()
            client = await self._ensure_client()
            signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)
            if (
                signing_key.algorithm_name != algorithm
                or signing_key.key_type != ("RSA" if algorithm == "RS256" else "EC")
                or signing_key.public_key_use not in (None, "sig")
            ):
                raise AuthenticationError()
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(_ALGORITHMS),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=30,
                options={"require": _REQUIRED_CLAIMS, "verify_nbf": True},
            )
            if claims.get("typ") != "Bearer":
                raise AuthenticationError("wrong_token_type")
            for name in ("exp", "iat", "nbf"):
                if name in claims and type(claims[name]) not in (int, float):
                    raise AuthenticationError()
            if claims["exp"] <= claims["iat"]:
                raise AuthenticationError()
            subject = claims.get("sub")
            kind = claims.get("c1_principal_kind")
            if not isinstance(subject, str) or kind not in {"human", "service"}:
                raise AuthenticationError()
            return Principal(
                issuer_alias=self.settings.issuer_alias,
                subject=subject,
                kind=kind,
            )
        except (AuthenticationError, jwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, AuthenticationError):
                raise
            raise AuthenticationError() from None

    async def ready(self) -> bool:
        try:
            uri = await self._discover()
            async with self._discovery_lock:
                if self._client is None or uri != self._jwks_uri:
                    self._client = _TrustedJWKClient(
                        uri,
                        cache_jwk_set=True,
                        cache_keys=False,
                        lifespan=300,
                        timeout=int(self.settings.backend_timeout_s),
                        cooldown_duration=0,
                    )
                    self._client.verify = self._verify
                    self._jwks_uri = uri
                client = self._client
            await asyncio.to_thread(client.get_jwk_set, refresh=True)
            return True
        except (AuthenticationError, jwt.PyJWTError, httpx.HTTPError, ValueError):
            return False

    async def close(self) -> None:
        await self._http.aclose()
