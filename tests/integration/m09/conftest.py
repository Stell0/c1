"""M09 real-service helpers: test-development packages over software-integration."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from scripts import software_producer as sp
from tests.integration.m03.conftest import LiveCase

PROFILE = {"profile": "test-development", "profile_version": "1"}
MAXIMUM = 524288
LEDGER = "`ledger.api`/create_invoice()."
SUBMIT = "`shop.client`/submit_order()."


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m09/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M09 real services require C1_STACK=1"))


def target(*snapshots: str, configuration: str | None = "default") -> dict[str, Any]:
    value: dict[str, Any] = {"snapshots": [sp.snapshot_id(key) for key in snapshots]}
    if configuration is not None:
        value["configurations"] = [sp.configuration_id(configuration)]
    return value


def body(
    anchor: str, snapshots: dict[str, Any], goal: str = "conformance", **extra: Any
) -> dict[str, Any]:
    return {
        **PROFILE,
        "anchor": {"id": anchor},
        "target": snapshots,
        "goal": goal,
        "budget": {"unit": "bytes", "maximum": MAXIMUM},
        **extra,
    }


async def request(
    case: LiveCase, actor: str, value: dict[str, Any], *, status: int = 200
) -> dict[str, Any]:
    response = await case.request("POST", "/v1/context", actor=actor, json=value)
    assert response.status_code == status, response.text
    return cast(dict[str, Any], response.json())


async def package(
    case: LiveCase, actor: str, anchor: str, snapshots: dict[str, Any], goal: str = "conformance"
) -> dict[str, Any]:
    """One complete package; the test budget is large enough for a single page."""
    value = await request(case, actor, body(anchor, snapshots, goal))
    assert value["outcome"] == "resolved", value
    assert value["bounds"]["next_cursor"] is None, value["bounds"]
    return value


def units(value: dict[str, Any], section: str | None = None) -> list[dict[str, Any]]:
    sections = value["structured"]["sections"]
    if section is not None:
        return cast(list[dict[str, Any]], sections[section])
    return [unit for name in sections for unit in sections[name]]


def unit_for(value: dict[str, Any], section: str, **match: Any) -> dict[str, Any]:
    found = [
        unit
        for unit in units(value, section)
        if all(unit.get(key) == expected for key, expected in match.items())
    ]
    assert len(found) == 1, (section, match, [unit.get("path") for unit in units(value, section)])
    return found[0]


def ledger_symbol(descriptors: str = LEDGER) -> str:
    return sp.symbol_id("ledger", descriptors)


def shop_symbol(descriptors: str = SUBMIT) -> str:
    return sp.symbol_id("shop", descriptors)


def volatile(value: Any, revision: str) -> Any:
    """Remove only declared volatility: the knowledge revision and signed cursors."""
    if isinstance(value, dict):
        return {
            key: volatile(item, revision)
            for key, item in value.items()
            if key not in {"revision", "next_cursor"}
        }
    if isinstance(value, list):
        return [volatile(item, revision) for item in value]
    if isinstance(value, str):
        return value.replace(revision, "<revision>")
    return value
