"""M07-T03: hidden paths, evidence and additions cannot change Dave's context."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m07.conftest import (
    assert_golden,
    canonical,
    install_batteries,
    mutate,
    package,
    serialized,
)


def test_t03_hidden_material_has_no_influence() -> None:
    async def run() -> None:
        async with live_case() as case:
            loaded = await install_batteries(case)
            ids = loaded["fixture"]["ids"]
            before = await package(case, loaded)
            public_bytes = serialized(before)
            for hidden in (
                ids["p-b4"],
                ids["prototype"],
                ids["hidden-part"],
                "P-B4",
                "Prototype-synthetic",
                "Hidden prototype appendix",
                "violet-electrolyte-token",
            ):
                assert hidden not in public_bytes
            carol = await package(case, loaded, actor="carol")
            assert ids["p-b4"] in serialized(carol)
            assert ids["prototype"] in serialized(carol)
            assert ids["hidden-part"] in serialized(carol)
            assert "violet-electrolyte-token" in serialized(carol)
            assert_golden(
                "context-carol.md", carol["markdown"], loaded["revision"], loaded["principals"]
            )
            for actor, status in (("dave", 404), ("carol", 200)):
                response = await case.request(
                    "GET", "/v1/resources/" + quote(ids["hidden-part"], safe=""), actor=actor
                )
                assert response.status_code == status, response.text
            await mutate(case, loaded, [loaded["fixture"]["hidden_topic"]])
            # Compare the new head too: hidden writes must not change any public
            # package field except the selected repository revision.
            after = await package(case, loaded, revision=await case.knowledge.head())
            assert canonical(before, before["revision"]) == canonical(after, after["revision"])

    asyncio.run(run())
