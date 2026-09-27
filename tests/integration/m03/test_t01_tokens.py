"""M03-T01: only intended Keycloak access tokens establish a principal."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import jwt
import pytest

from tests.integration.m03.conftest import bearer, live_case


def test_t01_real_issuer_audience_purpose_expiry_and_delegation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        async with live_case() as case:
            assert (await case.client.get("/v1/whoami")).status_code == 401
            assert (
                await case.client.get("/v1/whoami", headers={"Authorization": "Bearer malformed"})
            ).status_code == 401

            alice = await case.token("alice")
            valid = await case.client.get("/v1/whoami", headers=bearer(alice))
            assert valid.status_code == 200, valid.text
            identity = valid.json()
            assert identity["issuer_alias"] == "c1-dev"
            assert identity["kind"] == "human"
            assert isinstance(identity["subject"], str) and identity["subject"]
            assert "token" not in identity

            service = (await case.token_source.service("c1-svc-papertrader")).access
            service_result = await case.client.get("/v1/whoami", headers=bearer(service))
            assert service_result.status_code == 200, service_result.text
            assert service_result.json()["kind"] == "service"
            assert service_result.json()["subject"] != identity["subject"]

            wrong_issuer = (
                await case.token_source.user("outsider", client="c1-other-tests", realm="c1-other")
            ).access
            assert (
                await case.client.get("/v1/whoami", headers=bearer(wrong_issuer))
            ).status_code == 401

            no_audience = (await case.token_source.user("alice", client="c1-noaud")).access
            assert (
                await case.client.get("/v1/whoami", headers=bearer(no_audience))
            ).status_code == 401

            oidc = await case.token_source.user("alice", scope="openid")
            assert oidc.identity is not None
            assert (
                await case.client.get("/v1/whoami", headers=bearer(oidc.identity))
            ).status_code == 401

            delegated_header = await case.client.get(
                "/v1/whoami", headers={**bearer(alice), "X-On-Behalf-Of": "bob"}
            )
            delegated_body = await case.client.request(
                "GET", "/v1/whoami", headers=bearer(alice), json={"on_behalf_of": "bob"}
            )
            assert delegated_header.status_code == delegated_body.status_code == 200
            assert delegated_header.json() == delegated_body.json() == identity

            short = (await case.token_source.user("alice", client="c1-shortlived")).access
            claims = jwt.decode(short, options={"verify_signature": False})
            expiry = claims["exp"]
            assert isinstance(expiry, int)
            await asyncio.sleep(max(0.0, expiry + 31 - time.time()))
            assert (await case.client.get("/v1/whoami", headers=bearer(short))).status_code == 401

    with caplog.at_level(logging.INFO, logger="c1.audit"):
        asyncio.run(run())
    delegation = [
        json.loads(entry.message)
        for entry in caplog.records
        if entry.name == "c1.audit"
        and json.loads(entry.message).get("operation") == "attempted_delegation"
    ]
    assert len(delegation) == 2
    assert all(entry["outcome"] == "ignored" for entry in delegation)
    assert "Bearer " not in caplog.text
