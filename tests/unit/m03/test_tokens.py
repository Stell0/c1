"""M03-T01: signed bearer tokens are the only source of principal identity."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from c1.authorization.tokens import AuthenticationError, TokenValidator
from c1.config import Settings


def _settings(issuer: str) -> Settings:
    return Settings(
        instance_id="dev",
        instance_base="urn:c1:instance:dev:",
        issuer=issuer,
        issuer_alias="c1-dev",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token="test-only-token",
        fga_store="test-store",
        fga_model="test-model",
        terminus_url="http://127.0.0.1:16363",
        terminus_password="test-only-password",
        organization="admin",
        knowledge_database="test_knowledge",
        workflow_database="test_workflow",
        lock_path=Path("/tmp/c1-m03-token-test.lock"),
    )


@contextmanager
def oidc_server() -> Iterator[tuple[Settings, dict[str, Any], dict[str, Any]]]:
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ec_key = ec.generate_private_key(ec.SECP256R1())
    rsa_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    ec_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(ec_key.public_key()))
    rsa_jwk.update(kid="rsa-one", alg="RS256", use="sig")
    ec_jwk.update(kid="ec-one", alg="ES256", use="sig")
    state: dict[str, Any] = {
        "healthy": True,
        "issuer_override": None,
        "jwks_override": None,
        "keys": [rsa_jwk, ec_jwk],
        "requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state["requests"].append(self.path)
            if not state["healthy"]:
                self.send_error(503)
                return
            port = cast(ThreadingHTTPServer, self.server).server_port
            issuer = f"http://127.0.0.1:{port}/realms/test"
            if self.path == "/realms/test/.well-known/openid-configuration":
                payload = {
                    "issuer": state["issuer_override"] or issuer,
                    "jwks_uri": state["jwks_override"] or issuer + "/protocol/openid-connect/certs",
                }
            elif self.path == "/realms/test/protocol/openid-connect/certs":
                payload = {"keys": state["keys"]}
            else:
                self.send_error(404)
                return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        issuer = f"http://127.0.0.1:{server.server_port}/realms/test"
        yield _settings(issuer), {"rsa": rsa_key, "ec": ec_key}, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def claims(issuer: str, **changes: Any) -> dict[str, Any]:
    now = int(time.time())
    payload = {
        "iss": issuer,
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": ["account", "c1-api"],
        "iat": now - 60,
        "exp": now + 300,
        "typ": "Bearer",
        "c1_principal_kind": "human",
    }
    payload.update(changes)
    return payload


def sign(
    payload: dict[str, Any],
    key: Any,
    *,
    algorithm: str = "RS256",
    kid: str = "rsa-one",
    headers: dict[str, Any] | None = None,
) -> str:
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid, **(headers or {})})


def test_valid_human_service_and_ec_tokens() -> None:
    with oidc_server() as (settings, keys, _state):

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                human = await validator.authenticate(sign(claims(settings.issuer), keys["rsa"]))
                assert human.kind == "human"
                assert human.id == "user:c1-dev.00000000-0000-4000-8000-000000000001"
                service = await validator.authenticate(
                    sign(
                        claims(settings.issuer, c1_principal_kind="service", on_behalf_of="admin"),
                        keys["ec"],
                        algorithm="ES256",
                        kid="ec-one",
                    )
                )
                assert service.kind == "service"
                assert service.subject == human.subject
                assert await validator.ready()
            finally:
                await validator.close()

        asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "http://other.invalid/realms/test"},
        {"aud": "other-api"},
        {"typ": "ID"},
        {"c1_principal_kind": "robot"},
        {"sub": "admin:reader"},
        {"sub": ""},
        {"exp": None},
        {"iat": None},
    ],
)
def test_bad_signed_claims_rejected(change: dict[str, Any]) -> None:
    with oidc_server() as (settings, keys, _state):
        payload = claims(settings.issuer)
        payload.update(change)

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                with pytest.raises(AuthenticationError):
                    await validator.authenticate(sign(payload, keys["rsa"]))
            finally:
                await validator.close()

        asyncio.run(run())


def test_time_claims_use_thirty_second_leeway_and_optional_nbf() -> None:
    with oidc_server() as (settings, keys, _state):
        now = int(time.time())

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                accepted = claims(settings.issuer, iat=now - 60, exp=now - 15)
                assert (await validator.authenticate(sign(accepted, keys["rsa"]))).kind == "human"
                for payload in (
                    claims(settings.issuer, iat=now - 70, exp=now - 31),
                    claims(settings.issuer, nbf=now + 31),
                    claims(settings.issuer, iat=now + 31),
                ):
                    with pytest.raises(AuthenticationError):
                        await validator.authenticate(sign(payload, keys["rsa"]))
            finally:
                await validator.close()

        asyncio.run(run())


def test_wrong_keys_algorithms_and_tampering_rejected() -> None:
    with oidc_server() as (settings, keys, state):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        payload = claims(settings.issuer)
        valid = sign(payload, keys["rsa"])
        forged = sign(payload, other)
        wrong_alg = sign(payload, "secret-for-hs256-tests-only-long-enough", algorithm="HS256")
        none = jwt.encode(
            payload, key=cast(Any, None), algorithm="none", headers={"kid": "rsa-one"}
        )
        changed = valid.split(".")
        changed[1] = changed[1][:-1] + ("A" if changed[1][-1] != "A" else "B")
        tampered = ".".join(changed)
        external_key = sign(payload, keys["rsa"], headers={"jku": "http://127.0.0.1:9/jwks"})

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                for candidate in (forged, wrong_alg, none, tampered, external_key, "bad"):
                    with pytest.raises(AuthenticationError) as caught:
                        await validator.authenticate(candidate)
                    assert "secret" not in str(caught.value)
                assert all("/jwks" not in path for path in state["requests"])
            finally:
                await validator.close()

        asyncio.run(run())


def test_cached_known_key_survives_outage_but_unknown_key_denied() -> None:
    with oidc_server() as (settings, keys, state):
        known = sign(claims(settings.issuer), keys["rsa"])
        unknown = sign(claims(settings.issuer), keys["rsa"], kid="unknown")

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                await validator.authenticate(known)
                state["healthy"] = False
                assert (await validator.authenticate(known)).kind == "human"
                with pytest.raises(AuthenticationError):
                    await validator.authenticate(unknown)
                assert not await validator.ready()
            finally:
                await validator.close()

        asyncio.run(run())


def test_discovery_issuer_mismatch_fails_closed() -> None:
    with oidc_server() as (settings, keys, state):
        state["issuer_override"] = "http://other.invalid/realms/test"

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                assert not await validator.ready()
                with pytest.raises(AuthenticationError):
                    await validator.authenticate(sign(claims(settings.issuer), keys["rsa"]))
            finally:
                await validator.close()

        asyncio.run(run())


def test_discovery_cannot_redirect_jwks_to_another_origin() -> None:
    with oidc_server() as (settings, keys, state):
        state["jwks_override"] = "http://127.0.0.1:9/keys"

        async def run() -> None:
            validator = TokenValidator(settings)
            try:
                assert not await validator.ready()
                with pytest.raises(AuthenticationError):
                    await validator.authenticate(sign(claims(settings.issuer), keys["rsa"]))
                assert state["requests"] == [
                    "/realms/test/.well-known/openid-configuration",
                    "/realms/test/.well-known/openid-configuration",
                ]
            finally:
                await validator.close()

        asyncio.run(run())
