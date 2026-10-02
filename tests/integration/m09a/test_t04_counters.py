"""M09a-T04: backend work per request and ChangeSet step stays within ceilings."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from typing import Any

import pytest

from c1.authorization.journal import Journal
from c1.changes import profiles as catalog
from scripts import software_producer as sp
from tests.integration.m03.conftest import _all_tuples
from tests.integration.software import CaseLoader, Template, copy_of

TARGET = {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}


def test_t04_work_counters_on_the_software_fixture(
    software_template: Template, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            fga = case.runtime.fga
            calls: Counter[str] = Counter()
            original = type(fga)._request

            async def counted(self: Any, method: str, path: str, **kwargs: Any) -> Any:
                calls[path.rsplit("/", 1)[-1]] += 1
                return await original(self, method, path, **kwargs)

            monkeypatch.setattr(type(fga), "_request", counted)
            tuples = len(await _all_tuples(fga))
            calls.clear()
            response = await case.request(
                "POST", "/v1/software/lookup", actor="carol", json={"target": TARGET, "limit": 200}
            )
            assert response.status_code == 200, response.text
            pages = math.ceil(tuples / 100) + 1
            # Plan build and finalize each make one exact binding pass.
            assert calls["read"] <= 2 * pages, (calls, tuples)
            assert calls["list-objects"] <= 1

            # One producer ChangeSet: journal listings are per data version,
            # never per decision, and decisions are read from security views.
            listings: Counter[str] = Counter()
            original_list = Journal.list

            async def counted_list(self: Journal, kind: str) -> list[dict[str, Any]]:
                listings[kind] += 1
                return await original_list(self, kind)

            monkeypatch.setattr(Journal, "list", counted_list)
            records = [
                sp.entity(
                    sp.ident(f"m09a/capability/{index}", "entity"),
                    "Capability",
                    f"M09a {index}",
                    "sw-shared",
                )
                for index in range(20)
            ]
            loader = CaseLoader(case)
            calls.clear()
            await loader.apply_changeset(
                sp.operations(records),
                author="indexer",
                reviewer="reviewer",
                base=await case.knowledge.head(),
            )
            # Before M09a, one comparable ChangeSet made more than 1,000 listings.
            assert sum(listings.values()) <= 40, listings
            assert calls["check"] + calls["batch-check"] < 200, calls

            # Readiness parses no catalog file when nothing changed.
            assert await case.runtime.ready()
            before = len(catalog._PARSED)
            assert await case.runtime.ready()
            assert len(catalog._PARSED) == before

    asyncio.run(run())
