"""M07-T07: ambiguous selectors stay explicit and continuations reauthorize."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m07.conftest import (
    assert_golden,
    install_batteries,
    mutate,
    package,
    request_body,
    two_unit_page,
)


def test_t07_ambiguity_gaps_and_revoked_continuation() -> None:
    async def run() -> None:
        async with live_case() as case:
            loaded = await install_batteries(case)
            ids = loaded["fixture"]["ids"]
            await mutate(case, loaded, loaded["fixture"]["ambiguity"])
            loaded["revision"] = await case.knowledge.head()
            ambiguous = await package(case, loaded)
            assert ambiguous["outcome"] == "ambiguous"
            candidates = ambiguous["anchor_resolution"]["candidates"]
            assert {item["id"] for item in candidates} == {ids["tesla"], ids["ambiguous-person"]}
            assert "facts" not in ambiguous and "structured" not in ambiguous
            assert ids["hidden-tesla"] not in str(ambiguous)
            assert_golden("ambiguity.json", candidates, loaded["revision"])
            body = request_body(loaded, anchor={"id": ids["tesla"]})
            resolved = await package(case, loaded, anchor=body["anchor"])
            assert resolved["outcome"] == "resolved"
            unresolved = await package(
                case, loaded, anchor=body["anchor"], topics=["flux capacitors"]
            )
            assert unresolved["outcome"] == "unresolved"
            assert "structured" not in unresolved
            gaps = await package(case, loaded, anchor=body["anchor"], fields=["cycle_life"])
            assert gaps["structured"]["gaps"] == [
                {"field": "cycle_life", "message": "not present in the returned material"}
            ]
            assert "does not exist" not in gaps["markdown"]
            # Avoid the intentionally ambiguous label for the pagination test.
            first = await two_unit_page(case, loaded, anchor=body["anchor"])
            assert first["bounds"]["next_cursor"]
            dave = await case.principal("dave")
            revoke = await case.request(
                "DELETE",
                "/v1/access-scopes/"
                + quote(loaded["scopes"]["bat-robotelier"], safe="")
                + "/members/"
                + quote(dave.id, safe="")
                + "?role=reader",
                actor="erin",
            )
            assert revoke.status_code == 200, revoke.text
            continued = await case.request(
                "POST",
                "/v1/context",
                actor="dave",
                json={**body, "cursor": first["bounds"]["next_cursor"]},
            )
            assert continued.status_code == 409, continued.text
            assert continued.json()["code"] == "C1-CX-011"
            fresh = await package(case, loaded, anchor=body["anchor"])
            assert fresh["structured"]["facts"] == []

    asyncio.run(run())
