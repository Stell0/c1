"""Signed ID-token validation and optional browser capabilities."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from c1.config import ExplorerSettings
from c1.explorer.oidc import Endpoints, LoginError, OIDCClient
from c1.explorer.sessions import Tokens
from tests.unit.m03.test_tokens import claims, oidc_server, sign


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "nonce",
        "audience",
        "azp",
        "multi_audience",
        "access_type",
        "missing_sub",
        "bad_expiry",
        "future_iat",
    ],
)
def test_signed_id_tokens_require_nonce_audience_and_token_separation(failure: str | None) -> None:
    with oidc_server() as (settings, keys, _state):
        explorer = ExplorerSettings(
            origin="https://c1.example",
            client_id="explorer",
            client_secret="synthetic-client-credential",  # pragma: allowlist secret
        )
        payload = claims(settings.issuer, aud="explorer", typ="ID", nonce="expected-nonce")
        header = "JWT"
        if failure == "nonce":
            payload["nonce"] = "wrong"
        elif failure == "audience":
            payload["aud"] = "api"
        elif failure == "azp":
            payload["azp"] = "other-client"
        elif failure == "multi_audience":
            payload["aud"] = ["explorer", "other"]
        elif failure == "access_type":
            header = "at+jwt"
        elif failure == "missing_sub":
            payload.pop("sub")
        elif failure == "bad_expiry":
            payload["exp"] = payload["iat"]
        elif failure == "future_iat":
            payload["iat"] = time.time() + 300

        async def check() -> None:
            client = OIDCClient(settings.issuer, explorer, timeout_s=5)
            client._endpoints = Endpoints(
                settings.issuer + "/auth",
                settings.issuer + "/token",
                None,
                settings.issuer + "/protocol/openid-connect/certs",
            )
            try:
                token = sign(payload, keys["rsa"], headers={"typ": header})
                if failure:
                    with pytest.raises(LoginError):
                        await client._id_claims(token, "expected-nonce")
                else:
                    assert (await client._id_claims(token, "expected-nonce"))["sub"] == payload[
                        "sub"
                    ]
            finally:
                await client.close()

        asyncio.run(check())


def test_missing_provider_logout_does_not_block_discovery_or_local_termination() -> None:
    explorer = ExplorerSettings(
        origin="https://c1.example",
        client_id="explorer",
        client_secret="synthetic-client-credential",  # pragma: allowlist secret
    )  # pragma: allowlist secret

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/.well-known/openid-configuration")
        return httpx.Response(
            200,
            json={
                "issuer": "https://issuer.example/tenant",
                "authorization_endpoint": "https://issuer.example/auth",
                "token_endpoint": "https://issuer.example/token",
                "jwks_uri": "https://issuer.example/keys",
            },
        )

    async def check() -> None:
        client = OIDCClient("https://issuer.example/tenant", explorer, timeout_s=5)
        await client._http.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(serve))
        try:
            assert (await client.endpoints()).end_session is None
            assert await client.logout(Tokens("synthetic-access", time.monotonic() + 60)) is None
        finally:
            await client.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "field, advertised",
    [
        ("response_types_supported", ["id_token"]),
        ("token_endpoint_auth_methods_supported", ["client_secret_post"]),
        ("code_challenge_methods_supported", ["plain"]),
        ("id_token_signing_alg_values_supported", ["HS256"]),
    ],
)
def test_advertised_incompatible_provider_capabilities_are_actionable(
    field: str, advertised: list[str]
) -> None:
    explorer = ExplorerSettings(
        origin="https://c1.example",
        client_id="explorer",
        client_secret="synthetic-client-credential",  # pragma: allowlist secret
    )

    async def check() -> None:
        client = OIDCClient("https://issuer.example", explorer, timeout_s=5)
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(
                    200, json={"issuer": "https://issuer.example", field: advertised}
                )
            )
        )
        try:
            with pytest.raises(LoginError, match="unsupported_"):
                await client.endpoints()
        finally:
            await client.close()

    asyncio.run(check())


def test_refresh_without_replacement_preserves_only_previously_validated_credentials() -> None:
    explorer = ExplorerSettings(
        origin="https://c1.example",
        client_id="explorer",
        client_secret="synthetic-client-credential",  # pragma: allowlist secret
    )  # pragma: allowlist secret

    async def check() -> None:
        client = OIDCClient("https://issuer.example", explorer, timeout_s=5)
        client._endpoints = Endpoints(
            "https://issuer.example/auth",
            "https://issuer.example/token",
            None,
            "https://issuer.example/keys",
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(
                    200,
                    json={
                        "token_type": "Bearer",
                        "access_token": "new-synthetic-access",
                        "expires_in": 60,
                    },
                )
            )
        )
        tokens = Tokens(
            "old-synthetic-access",
            time.monotonic() + 1,
            refresh_token="synthetic-refresh",
            identity_token="validated-original-id",
        )
        try:
            result = await client.refresh(tokens)
            assert result.refresh_token == tokens.refresh_token
            assert result.identity_token == tokens.identity_token
        finally:
            await client.close()

    asyncio.run(check())
