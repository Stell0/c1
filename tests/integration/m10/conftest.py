"""M10 real-service helpers: two-stage support requests on the software templates."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from scripts import software_producer as sp
from tests.integration.m03.conftest import LiveCase

MAXIMUM = 524288
CREATE = sp.operation_id("ledger", "createInvoice")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m10/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M10 real services require C1_STACK=1"))


def target(*snapshots: str) -> dict[str, Any]:
    return {
        "snapshots": [sp.snapshot_id(key) for key in snapshots],
        "configurations": [sp.configuration_id("default")],
    }


def documentation(
    snapshots: dict[str, Any], aspects: list[str] | None = None, anchor: str = CREATE
) -> dict[str, Any]:
    return {
        "profile": "support-documentation",
        "profile_version": "1",
        "anchor": {"id": anchor},
        "target": snapshots,
        "aspects": aspects or [],
        "budget": {"unit": "bytes", "maximum": MAXIMUM},
    }


def implementation(
    snapshots: dict[str, Any], aspects: list[str], token: str | None = None, anchor: str = CREATE
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "profile": "support-implementation",
        "profile_version": "1",
        "anchor": {"id": anchor},
        "target": snapshots,
        "aspects": aspects,
        "budget": {"unit": "bytes", "maximum": MAXIMUM},
    }
    if token is not None:
        value["followup_token"] = token
    return value


async def context(
    case: LiveCase, actor: str, body: dict[str, Any], *, status: int = 200
) -> dict[str, Any]:
    response = await case.request("POST", "/v1/context", actor=actor, json=body)
    assert response.status_code == status, response.text
    return cast(dict[str, Any], response.json())


def section(value: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], value["structured"]["sections"][name])


def missing(value: dict[str, Any]) -> list[str]:
    return [item["aspect"]["label"] for item in value["structured"]["missing_aspects"]]


def titles(units: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for unit in units:
        title = unit.get("document_title") or unit.get("document", {}).get("title")
        if title not in seen:
            seen.append(title)
    return seen
