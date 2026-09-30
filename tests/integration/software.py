"""Shared software-integration load for M08 and M09 real-service tests.

The session fixture `software` is registered by `tests/integration/conftest.py`,
so every directory that uses it shares one load per session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

import pytest

from scripts import software_producer as sp
from scripts.load_fixture import SERVICE_ACTORS, Loader
from tests.integration.m03.conftest import LiveCase, live_case


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


@pytest.fixture(scope="session")
def software() -> Iterator[Software]:
    with asyncio.Runner() as runner:
        context = live_case()
        case = runner.run(context.__aenter__())
        try:
            yield Software(runner, case, runner.run(load(case)))
        finally:
            runner.run(context.__aexit__(None, None, None))


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
