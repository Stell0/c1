"""M05-T06: query bounds and errors fail closed through the public API."""

from __future__ import annotations

import asyncio
import os
from typing import cast
from urllib.parse import quote

import pytest

from tests.integration.m04.conftest import C1, entity_record, live_case, seeded_scope

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]


def test_t06_limits_reject_oversized_page_depth_and_backend_query_text() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M05-T06 limits")
            record = entity_record(label="Visible limits fixture")
            await case.provision(record, scope)
            path = "/v1/entities/" + quote(record.id, safe="") + "/neighborhood"
            oversized = await case.request(
                "GET", "/v1/entities", actor="alice", params={"limit": 201}
            )
            assert oversized.status_code == 422, oversized.text
            malformed_boolean = await case.request(
                "GET", "/v1/entities", actor="alice", params={"include_unknown": "yes"}
            )
            assert malformed_boolean.status_code == 400, malformed_boolean.text
            assert malformed_boolean.json()["code"] == "C1-QY-001"
            too_deep = await case.request(
                "GET",
                path,
                actor="alice",
                params={"predicates": C1 + "worksFor", "depth": 4},
            )
            assert too_deep.status_code == 422, too_deep.text
            for key in ("graphql", "woql", "sparql", "query"):
                forbidden = await case.request(
                    "GET", "/v1/entities", actor="alice", params={key: "{secret}"}
                )
                assert forbidden.status_code == 400, forbidden.text
                assert forbidden.json()["code"] == "C1-QY-002"

    asyncio.run(run())


def test_t06_hidden_and_nonexistent_are_indistinguishable() -> None:
    async def run() -> None:
        async with live_case() as case:
            private = await case.scope("M05-T06 hidden")
            hidden = entity_record(label="Hidden from Alice")
            await case.provision(hidden, private)
            path = "/v1/entities/" + quote(hidden.id, safe="")
            denied = await case.request("GET", path, actor="alice")
            nonexistent = await case.request(
                "GET",
                "/v1/entities/" + quote("urn:c1:instance:dev:entity/nonexistent", safe=""),
                actor="alice",
            )
            assert denied.status_code == nonexistent.status_code == 404
            assert denied.content == nonexistent.content
            malformed = await case.request("GET", "/v1/entities/not-an-iri", actor="alice")
            assert malformed.status_code == 400, malformed.text
            assert "Hidden from Alice" not in malformed.text

    asyncio.run(run())


def test_t06_deadline_returns_503_without_partial_items(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await seeded_scope(case, "M05-T06 deadline")
            await case.provision(entity_record(label="Slow query fixture"), scope)
            original_head = case.runtime.knowledge.head

            async def slow_head() -> str:
                await asyncio.sleep(case.settings.query_time_budget_ms / 1000 + 0.1)
                return cast(str, await original_head())

            monkeypatch.setattr(case.runtime.knowledge, "head", slow_head)
            try:
                response = await case.request("GET", "/v1/entities", actor="alice")
            finally:
                monkeypatch.setattr(case.runtime.knowledge, "head", original_head)
            assert response.status_code == 503, response.text
            assert response.json()["code"] == "C1-QY-053"
            assert "items" not in response.json()

    asyncio.run(run())
