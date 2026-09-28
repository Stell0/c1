"""Document transport preserves IRIs, including operation-like final segments."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest

from c1.api import create_app
from c1.authorization.principal import Principal
from c1.authorization.tokens import AuthenticationError
from c1.config import Settings
from c1.runtime import Runtime

PRINCIPAL = Principal("test", "alice", "human")
HEADERS = {"Authorization": "Bearer good"}


@pytest.fixture
def runtime(tmp_path: Path) -> SimpleNamespace:
    settings = Settings(
        instance_id="c1test",
        instance_base="urn:c1:instance:test:",
        issuer="http://127.0.0.1:18090/realms/test",
        issuer_alias="test",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token="synthetic",
        fga_store="test-store",
        fga_model="test-model",
        terminus_url="http://127.0.0.1:16363",
        terminus_password="synthetic",
        organization="admin",
        knowledge_database="knowledge_test",
        workflow_database="workflow_test",
        lock_path=tmp_path / "lock",
    )

    def authenticate(token: str) -> Principal:
        if token != "good":
            raise AuthenticationError()
        return PRINCIPAL

    return SimpleNamespace(
        settings=settings,
        tokens=SimpleNamespace(authenticate=AsyncMock(side_effect=authenticate)),
        audit=SimpleNamespace(emit=Mock()),
        documents=SimpleNamespace(
            detail=AsyncMock(return_value={"document": {"id": "synthetic"}, "parts": []}),
            parts=AsyncMock(return_value={"parts": []}),
            render=AsyncMock(return_value={"content": "synthetic"}),
            export=AsyncMock(return_value={"records": []}),
            history=AsyncMock(return_value={"items": []}),
        ),
        start=AsyncMock(),
        close=AsyncMock(),
    )


@asynccontextmanager
async def _client(runtime: SimpleNamespace) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(runtime.settings, runtime=cast(Runtime, runtime))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client


@pytest.mark.parametrize("suffix", ["parts", "render", "export", "history"])
def test_by_id_reads_full_suffix_ending_iri(runtime: SimpleNamespace, suffix: str) -> None:
    async def case() -> None:
        identifier = "https://example.test/manual/" + suffix
        async with _client(runtime) as client:
            response = await client.get(
                "/v1/documents/by-id",
                params={"document_id": identifier, "revision": "commit:old"},
                headers=HEADERS,
            )
        assert response.status_code == 200, response.text
        runtime.documents.detail.assert_awaited_once_with(
            PRINCIPAL, identifier, revision="commit:old"
        )
        for operation in ("parts", "render", "export", "history"):
            getattr(runtime.documents, operation).assert_not_awaited()
        event = runtime.audit.emit.call_args.kwargs
        assert event["operation"] == "document_read"
        assert event["target"] == identifier and event["principal"] == PRINCIPAL.id

    asyncio.run(case())


def test_normal_path_detail_is_unchanged(runtime: SimpleNamespace) -> None:
    async def case() -> None:
        identifier = "urn:c1:instance:test:document/00000061-0000-4000-8000-000000000000"
        async with _client(runtime) as client:
            response = await client.get(
                "/v1/documents/" + quote(identifier, safe=""), headers=HEADERS
            )
        assert response.status_code == 200, response.text
        runtime.documents.detail.assert_awaited_once_with(PRINCIPAL, identifier, revision=None)

    asyncio.run(case())


@pytest.mark.parametrize("operation", ["parts", "render", "export", "history"])
def test_operation_paths_keep_full_decoded_target(runtime: SimpleNamespace, operation: str) -> None:
    async def case() -> None:
        identifier = "https://example.test/manual/render"
        async with _client(runtime) as client:
            response = await client.get(
                "/v1/documents/" + quote(identifier, safe="") + "/" + operation,
                headers=HEADERS,
            )
        assert response.status_code == 200, response.text
        method = getattr(runtime.documents, operation)
        method.assert_awaited_once()
        assert method.await_args.args == (PRINCIPAL, identifier)
        runtime.documents.detail.assert_not_awaited()

    asyncio.run(case())


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("", "C1-QY-001"),
        ("document_id=", "C1-QY-001"),
        ("document_id=urn:test:doc&unknown=value", "C1-QY-001"),
        ("document_id=urn:test:doc&document_id=urn:test:other", "C1-QY-001"),
        ("document_id=urn:test:doc&revision=old&revision=new", "C1-QY-001"),
        ("document_id=urn:test:doc&query=value", "C1-QY-002"),
        ("document_id=urn:test:doc&database=other", "C1-QY-001"),
        ("document_id=urn:test:doc&format=text", "C1-QY-001"),
        ("document_id=urn:test:doc&revision=invalid!", "C1-DC-011"),
    ],
)
def test_by_id_rejects_invalid_selectors(runtime: SimpleNamespace, query: str, code: str) -> None:
    async def case() -> None:
        async with _client(runtime) as client:
            response = await client.get("/v1/documents/by-id?" + query, headers=HEADERS)
        assert response.status_code == 400, response.text
        assert response.json()["code"] == code
        runtime.documents.detail.assert_not_awaited()

    asyncio.run(case())


@pytest.mark.parametrize("token", [None, "invalid"])
def test_by_id_requires_authentication(runtime: SimpleNamespace, token: str | None) -> None:
    async def case() -> None:
        headers = {"Authorization": "Bearer " + token} if token is not None else {}
        async with _client(runtime) as client:
            response = await client.get(
                "/v1/documents/by-id", params={"document_id": "urn:test:doc"}, headers=headers
            )
        assert response.status_code == 401, response.text
        runtime.documents.detail.assert_not_awaited()

    asyncio.run(case())
