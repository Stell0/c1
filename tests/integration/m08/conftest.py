"""M08 real-service fixture: the software-integration load, shared by read checks."""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.integration.m03.conftest import LiveCase
from tests.integration.software import (
    CaseLoader,
    Software,
    commit,
    fresh_tokens,
    load,
    producer,
    revision_after,
    snapshot,
    symbol,
)

# Helpers moved to tests/integration/software.py in M09 remain importable here.
__all__ = [
    "CaseLoader",
    "Software",
    "commit",
    "fresh_tokens",
    "load",
    "lookup",
    "lookup_all",
    "producer",
    "resolve",
    "revision_after",
    "snapshot",
    "symbol",
]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m08/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M08 real services require C1_STACK=1"))


async def lookup(case: LiveCase, actor: str, body: dict[str, Any], *, status: int = 200) -> Any:
    response = await case.request("POST", "/v1/software/lookup", actor=actor, json=body)
    assert response.status_code == status, response.text
    return response.json()


async def lookup_all(case: LiveCase, actor: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Follow reauthorized continuation to collect every item."""
    items: list[dict[str, Any]] = []
    page = await lookup(case, actor, {**body, "limit": 200})
    items.extend(page["items"])
    while page["next_cursor"]:
        page = await lookup(case, actor, {**body, "limit": 200, "cursor": page["next_cursor"]})
        items.extend(page["items"])
    assert len(items) == page["count"]
    return items


async def resolve(case: LiveCase, actor: str, body: dict[str, Any], *, status: int = 200) -> Any:
    response = await case.request("POST", "/v1/software/targets/resolve", actor=actor, json=body)
    assert response.status_code == status, response.text
    return response.json()
