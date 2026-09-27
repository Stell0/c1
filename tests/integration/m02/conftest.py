"""Real TerminusDB fixtures for M02; a skipped test is not gate evidence."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import StorageConfig, Terminus
from probes.config import Settings

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "fixtures/core-knowledge"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m02/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M02 live stack requires C1_STACK=1"))


def fixture_payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURE_ROOT / "fixture.jsonld").read_text()))


def expected(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / "expected" / name).read_text())


@asynccontextmanager
async def live_knowledge(registry: ProfileRegistry | None = None) -> AsyncIterator[Terminus]:
    settings = Settings.load()
    config = StorageConfig(
        url=settings.terminus_url,
        password=settings.terminus_password,
        organization="admin",
        database=f"c1_m02_{uuid.uuid4().hex}",
        instance_base="urn:c1:instance:dev:",
    )
    async with Terminus(config) as db:
        await db.create()
        try:
            await db.install_profile(registry or ProfileRegistry())
            yield db
        finally:
            await db.drop()
