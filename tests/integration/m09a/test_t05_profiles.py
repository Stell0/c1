"""M09a-T05: cached catalog parsing never hides an installed-schema change."""

from __future__ import annotations

import asyncio

from c1.changes.profiles import _marker_id
from tests.integration.software import Template, copy_of


def test_t05_marker_removal_fails_readiness_despite_cached_candidates(
    software_template: Template,
) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            runtime = case.runtime
            assert await runtime.ready()
            assert await runtime.ready()  # served from cached candidates
            marker = _marker_id(runtime.registry, case.knowledge, "software")
            head = await case.knowledge.head()
            await case.knowledge._request(
                "DELETE",
                case.knowledge._document_path,
                params={"id": marker, "author": "m09a", "message": "remove marker"},
            )
            assert await case.knowledge.head() != head
            assert not await runtime.ready()

    asyncio.run(run())
