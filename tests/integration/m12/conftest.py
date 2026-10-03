"""Shared M12 helpers: fixture loading through the API, audit capture, and lookups."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m05.test_t01_directory import _setup_directory

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "fixtures/directory/fixture.json"
PERSON = "urn:c1:instance:dev:entity/00000013-0000-4000-8000-000000000000"
COMPANY_A = "urn:c1:instance:dev:entity/00000011-0000-4000-8000-000000000000"
PHONE = "urn:c1:ns:directory#hasPhone"


class AuditTap:
    """Records every API audit event of one case (principal and operation only)."""

    def __init__(self, case: LiveCase) -> None:
        self.events: list[dict[str, str]] = []
        audit = case.runtime.audit
        original = audit.emit

        def emit(*args: Any, **kwargs: Any) -> Any:
            names = ("principal", "operation", "target", "outcome", "reason", "correlation_id")
            values = dict(zip(names, args, strict=False))
            values.update(kwargs)
            self.events.append({k: str(values.get(k, "")) for k in names})
            return original(*args, **kwargs)

        audit.emit = emit

    def operations(self, principal: str, *, outcome: str = "allowed") -> list[str]:
        return [
            e["operation"]
            for e in self.events
            if e["principal"] == principal and e["outcome"] == outcome
        ]

    def mark(self) -> int:
        return len(self.events)

    def since(self, mark: int) -> list[dict[str, str]]:
        return self.events[mark:]


def directory_fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(DIRECTORY.read_text(encoding="utf-8")))


async def scope_ids(case: LiveCase) -> dict[str, str]:
    """Scope labels to IDs, read as the fixture's scope administrator (erin)."""
    response = await case.request("GET", "/v1/access-scopes", actor="erin")
    assert response.status_code == 200, response.text
    return {item["label"]: item["id"] for item in response.json()["access_scopes"]}


@asynccontextmanager
async def directory_case() -> AsyncIterator[tuple[LiveCase, dict[str, str]]]:
    """A fresh case with the directory fixture loaded through the ordinary API (M05)."""
    fixture = directory_fixture()
    async with live_case() as case:
        await _setup_directory(case, fixture)
        labels = await scope_ids(case)
        yield case, {name: labels[label] for name, label in fixture["scopes"].items()}


async def grant(case: LiveCase, scope: str, member: str, *roles: str) -> None:
    for role in roles:
        await case.grant(scope, member, role)


async def resource(case: LiveCase, identifier: str, actor: str) -> dict[str, Any]:
    response = await case.request("GET", "/v1/resources/" + quote(identifier, safe=""), actor=actor)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())
