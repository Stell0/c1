"""Shared software-integration loads for M08 and M09 real-service tests.

A session loads the fixture at most twice through the real producer path:
once as loaded, and once as the twin without restricted-scope records. Each
load becomes a template. Every test that needs its own repository gets a fresh
copy of a template instead of a new load. The shared `software` case is also a
copy, so tests that write to it never alter a template. The session fixtures
are registered by `tests/integration/conftest.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest

from scripts import software_producer as sp
from scripts.load_fixture import SERVICE_ACTORS, Loader
from tests.integration.m03.conftest import (
    CaseTemplate,
    LiveCase,
    capture_template,
    live_case,
)


class CaseLoader(Loader):
    def __init__(self, case: LiveCase) -> None:
        super().__init__(case.client, {}, refresh_tokens=True)
        self.case = case

    async def _actor_token(self, actor: str) -> str:
        if actor in SERVICE_ACTORS:
            return (await self.case.token_source.service("c1-svc-" + SERVICE_ACTORS[actor])).access
        name = {"admin": "erin", "reviewer": "carol"}.get(actor, actor)
        return (await self.case.token_source.user(name)).access


@dataclass
class Software:
    runner: asyncio.Runner
    case: LiveCase
    loaded: dict[str, Any]

    @property
    def fixture(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.loaded["planner"].fixture)

    def run(self, coroutine: Any) -> Any:
        return self.runner.run(coroutine)


def fresh_tokens(case: LiveCase) -> None:
    """Loads outlive access-token lifetimes; fetch a current token per request."""

    async def token(name: str) -> str:
        return (await case.token_source.user(name)).access

    cast(Any, case).token = token


async def load(
    case: LiveCase, transform: Callable[[list[sp.Run]], list[sp.Run]] | None = None
) -> dict[str, Any]:
    fresh_tokens(case)
    return await sp.load_software_integration(CaseLoader(case), transform=transform)


@dataclass(frozen=True)
class Template:
    """A loaded repository that tests copy; `loaded` stays valid in every copy."""

    case: CaseTemplate
    loaded: dict[str, Any]


def _template(transform: Callable[[list[sp.Run]], list[sp.Run]] | None) -> Iterator[Template]:
    with asyncio.Runner() as runner:
        context = live_case()
        case = runner.run(context.__aenter__())
        try:
            loaded = runner.run(load(case, transform))
            yield Template(runner.run(capture_template(case)), loaded)
        finally:
            runner.run(context.__aexit__(None, None, None))


@pytest.fixture(scope="session")
def software_template() -> Iterator[Template]:
    """The fixture loaded once through the real producer path."""
    yield from _template(None)


@pytest.fixture(scope="session")
def software_twin_template() -> Iterator[Template]:
    """The same load as if restricted-scope records had never been written."""
    yield from _template(lambda runs: sp.without_scopes(runs, {"sw-restricted"}))


@pytest.fixture(scope="session")
def software(software_template: Template) -> Iterator[Software]:
    with asyncio.Runner() as runner:
        context = live_case(software_template.case)
        case = runner.run(context.__aenter__())
        fresh_tokens(case)
        try:
            yield Software(runner, case, software_template.loaded)
        finally:
            runner.run(context.__aexit__(None, None, None))


@asynccontextmanager
async def copy_of(template: Template) -> AsyncIterator[LiveCase]:
    """A fresh, independent repository that starts as a copy of the template."""
    async with live_case(template.case) as case:
        fresh_tokens(case)
        yield case


def snapshot(key: str) -> str:
    return sp.snapshot_id(key)


def symbol(repository: str, descriptors: str) -> str:
    return sp.symbol_id(repository, descriptors)


def commit(software: Software, key: str) -> str:
    return str(software.fixture["snapshots"][key]["commit"])


def revision_after(software: Software, run_key: str) -> str:
    for outcome in software.loaded["runs"]:
        if outcome["run"] == run_key:
            return str(outcome["revision_after"])
    raise AssertionError(run_key)


def producer(software: Software, actor: str) -> str:
    return str(software.loaded["principals"][actor])
