"""Validate only access tokens from the configured OIDC issuer."""

from __future__ import annotations

import asyncio
import math
import ssl
from typing import Any, Literal, cast

import httpx
import jwt
from jwt import PyJWKClient

from c1 import roundtrips
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.oidc import trusted_endpoint

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
        if not trusted_endpoint(jwks_uri, self.settings.issuer, self.settings.oidc_endpoint_urls):
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
            required = list(_REQUIRED_CLAIMS)
            if self.settings.oidc_token_profile in {"rfc9068-v1", "hydra-jwt-v1"}:
                types = (
                    {"at+jwt", "application/at+jwt"}
                    if (self.settings.oidc_token_profile == "rfc9068-v1")
                    else {"JWT"}
                )
                if not isinstance(header.get("typ"), str) or header["typ"] not in types:
                    raise AuthenticationError("wrong_token_type")
                required.extend(["client_id", "jti"])
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(_ALGORITHMS),
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=30,
                options={"require": required, "verify_nbf": True},
            )
            if self.settings.oidc_token_profile == "c1-v1" and claims.get("typ") != "Bearer":
                raise AuthenticationError("wrong_token_type")
            if claims.get("typ") == "ID" or claims.get("token_use") == "id":
                raise AuthenticationError("wrong_token_type")
            if self.settings.oidc_token_profile in {"rfc9068-v1", "hydra-jwt-v1"} and any(
                not isinstance(claims[name], str) or not claims[name]
                for name in ("client_id", "jti")
            ):
                raise AuthenticationError()
            for name in ("exp", "iat", "nbf"):
                if name in claims and (
                    type(claims[name]) not in (int, float) or not math.isfinite(claims[name])
                ):
                    raise AuthenticationError()
            if claims["exp"] <= claims["iat"]:
                raise AuthenticationError()
            subject = claims.get("sub")
            kind_claims = claims
            if self.settings.oidc_token_profile == "hydra-jwt-v1":
                extra = claims.get("ext")
                if not isinstance(extra, dict) or extra.get("token_use") != "access":
                    raise AuthenticationError("wrong_token_type")
                kind_claims = extra
            raw_kind = kind_claims.get(self.settings.principal_kind_claim)
            if not isinstance(raw_kind, str):
                raise AuthenticationError()
            kind = dict(self.settings.principal_kind_mapping).get(raw_kind)
            if not isinstance(subject, str) or kind not in {"human", "service"}:
                raise AuthenticationError()
            try:
                return Principal(
                    issuer_alias=self.settings.issuer_alias,
                    subject=subject,
                    kind=cast(Literal["human", "service"], kind),
                )
            except ValueError:
                raise AuthenticationError("unsupported_subject") from None
        except (
            AuthenticationError,
            jwt.PyJWTError,
            httpx.HTTPError,
            ValueError,
            OverflowError,
        ) as exc:
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
            keys = await asyncio.to_thread(client.get_jwk_set, refresh=True)
            return any(
                key.algorithm_name in _ALGORITHMS and key.public_key_use in (None, "sig")
                for key in keys.keys
            )
        except (AuthenticationError, jwt.PyJWTError, httpx.HTTPError, ValueError):
            return False

    async def close(self) -> None:
        await self._http.aclose()
