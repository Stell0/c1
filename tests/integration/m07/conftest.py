"""M07 real-service fixture, shared only by read-only acceptance checks."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from scripts.demo_m07 import expected_actors
from scripts.load_fixture import Loader, fixture_operations
from tests.integration.m03.conftest import LiveCase, live_case

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = ROOT / "fixtures/cross-project-batteries/expected"
B = "urn:c1:ns:batteries#"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m07/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M07 real services require C1_STACK=1"))


class CaseLoader(Loader):
    def __init__(self, case: LiveCase) -> None:
        super().__init__(case.client, {}, refresh_tokens=True)
        self.case = case

    async def _actor_token(self, actor: str) -> str:
        if actor in {"service", "robotelier"}:
            client = "c1-svc-papertrader" if actor == "service" else "c1-svc-robotelier"
            return (await self.case.token_source.service(client)).access
        name = {"admin": "erin", "reviewer": "carol"}.get(actor, actor)
        return (await self.case.token_source.user(name)).access


async def install_batteries(case: LiveCase) -> dict[str, Any]:
    async def fresh_token(name: str) -> str:
        return (await case.token_source.user(name)).access

    cast(Any, case).token = fresh_token
    return await CaseLoader(case).load_batteries()


@dataclass
class Batteries:
    runner: asyncio.Runner
    case: LiveCase
    loaded: dict[str, Any]


@pytest.fixture(scope="session")
def batteries() -> Iterator[Batteries]:
    # One persistent event loop owns the clients for all read-only checks.
    # T03 and T07 use their own isolated databases for writes/revocation.
    with asyncio.Runner() as runner:
        context = live_case()
        case = runner.run(context.__aenter__())
        try:
            loaded = runner.run(install_batteries(case))
            yield Batteries(runner, case, loaded)
        finally:
            runner.run(context.__aexit__(None, None, None))


def request_body(loaded: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "profile": "graph-context",
        "profile_version": "1",
        "anchor": {"label": "Tesla"},
        "topics": ["batteries"],
        "revision": loaded["revision"],
        **changes,
    }


async def package(
    case: LiveCase, loaded: dict[str, Any], *, actor: str = "dave", **changes: Any
) -> dict[str, Any]:
    response = await case.request(
        "POST", "/v1/context", actor=actor, json=request_body(loaded, **changes)
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def canonical(value: Any, revision: str | None = None) -> Any:
    """Normalize only declared transport/time/revision volatility."""
    if isinstance(value, dict):
        return {
            key: canonical(item, revision)
            for key, item in value.items()
            if key not in {"generated_at", "request_id", "revision"}
        }
    if isinstance(value, list):
        return [canonical(item, revision) for item in value]
    if isinstance(value, str) and revision:
        return value.replace(revision, "<revision>")
    return value


def serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def mutate(case: LiveCase, loaded: dict[str, Any], records: list[dict[str, Any]]) -> None:
    loader = CaseLoader(case)
    await loader.apply_changeset(
        fixture_operations(records, loaded["scopes"], loaded["principals"]),
        author="robotelier",
        reviewer="reviewer",
        base=await case.knowledge.head(),
    )


def assert_golden(
    name: str, value: Any, revision: str, principals: dict[str, str] | None = None
) -> None:
    path = EXPECTED / name
    assert path.is_file(), f"Reviewed golden is missing: {path}"
    normalized = canonical(value, revision)
    expected = (
        json.loads(path.read_text(encoding="utf-8"))
        if name.endswith(".json")
        else path.read_text(encoding="utf-8")
    )
    expected = expected_actors(
        expected, principals or {}, encode=False, markdown=name.endswith(".md")
    )
    assert normalized == expected


async def two_unit_page(case: LiveCase, loaded: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """Measure an API byte boundary; never assume a synthetic unit's size."""
    full = await package(case, loaded, **changes)
    low, high = 2048, full["bounds"]["rendered_bytes"]
    while low <= high:
        maximum = (low + high) // 2
        response = await case.request(
            "POST",
            "/v1/context",
            actor="dave",
            json=request_body(loaded, **changes, budget={"unit": "bytes", "maximum": maximum}),
        )
        if response.status_code == 422:
            assert response.json()["code"] == "C1-CX-010", response.text
            low = maximum + 1
            continue
        assert response.status_code == 200, response.text
        value = cast(dict[str, Any], response.json())
        count = len(value["structured"]["facts"])
        if count == 2:
            # Set the exact full-rendering boundary rather than keeping the
            # incidental binary-search maximum. Cursor byte length is stable.
            measured = value["bounds"]["rendered_bytes"]
            return await package(
                case, loaded, **changes, budget={"unit": "bytes", "maximum": measured}
            )
        if count < 2:
            low = maximum + 1
        else:
            high = maximum - 1
    raise AssertionError("No whole-rendering budget includes exactly two fixture units")
