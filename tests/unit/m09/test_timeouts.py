"""M09 D12–D13: request budget default and configurable backend timeouts."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from c1.authorization.fga import FGA
from c1.authorization.tokens import TokenValidator
from tests.unit.m03.test_tokens import _settings


def test_defaults_keep_backend_timeouts_and_raise_request_budget() -> None:
    settings = _settings("https://issuer.example")
    assert settings.query_time_budget_ms == 10000
    assert settings.backend_timeout_s == 5.0


@pytest.mark.parametrize("value", [0.5, 31.0])
def test_backend_timeout_is_bounded(value: float) -> None:
    with pytest.raises(ValueError):
        replace(_settings("https://issuer.example"), backend_timeout_s=value)


def test_timeouts_reach_the_backend_clients() -> None:
    async def run() -> None:
        settings = replace(_settings("https://issuer.example"), backend_timeout_s=12.0)
        async with FGA("http://127.0.0.1:1", "token", timeout=12.0) as fga:
            assert fga._client.timeout.read == 12.0
        validator = TokenValidator(settings)
        assert validator._http.timeout.read == 12.0
        await validator._http.aclose()

    asyncio.run(run())
