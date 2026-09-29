"""The new read-only context transport keeps shared authentication and limits."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from c1.context.errors import ContextError
from c1.context.request import ContextRequest
from tests.unit.m06.test_document_routes import HEADERS, PRINCIPAL, _client
from tests.unit.m06.test_document_routes import runtime as runtime  # noqa: F401

BODY = {"profile": "graph-context", "profile_version": "1", "anchor": {"label": "Tesla"}}


@pytest.mark.parametrize("authorization", [None, "Bearer bad"])
def test_context_requires_shared_authentication(
    runtime: SimpleNamespace, authorization: str | None
) -> None:
    runtime.context = SimpleNamespace(build=AsyncMock())

    async def run() -> None:
        async with _client(runtime) as client:
            response = await client.post(
                "/v1/context",
                json=BODY,
                headers={} if authorization is None else {"Authorization": authorization},
            )
        assert response.status_code == 401
        runtime.context.build.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"query": "arbitrary backend query"},
        {"budget": {"unit": "bytes", "maximum": 0}},
        {"profile_version": "unrecognized", "extra": True},
    ],
)
def test_context_rejects_unsupported_body_before_selection(
    runtime: SimpleNamespace, changes: dict[str, Any]
) -> None:
    runtime.context = SimpleNamespace(build=AsyncMock())

    async def run() -> None:
        async with _client(runtime) as client:
            response = await client.post("/v1/context", json={**BODY, **changes}, headers=HEADERS)
        assert response.status_code == 400
        assert response.json()["code"] == "C1-CX-001"
        runtime.context.build.assert_not_awaited()

    asyncio.run(run())


def test_context_dispatches_same_principal_and_explicit_minimum(runtime: SimpleNamespace) -> None:
    runtime.context = SimpleNamespace(
        build=AsyncMock(
            side_effect=ContextError(
                422, "C1-CX-010", "minimum_budget", details={"minimum_required": 4096}
            )
        )
    )

    async def run() -> None:
        async with _client(runtime) as client:
            response = await client.post("/v1/context", json=BODY, headers=HEADERS)
        assert response.status_code == 422
        assert response.json()["minimum_required"] == 4096
        runtime.context.build.assert_awaited_once_with(
            PRINCIPAL, ContextRequest.model_validate(BODY)
        )

    asyncio.run(run())
