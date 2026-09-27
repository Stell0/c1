"""M05-T03: hidden resources never affect observable search or traversal."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from urllib.parse import quote

import pytest

from c1.model.keywords import Keyword
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1
from tests.integration.m03.conftest import (
    LiveCase,
    entity_record,
    live_case,
    relation_record,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]

XSD = "http://www.w3.org/2001/XMLSchema#"


def _keyword(text: str) -> NodeRecord:
    keyword = Keyword(text=text, language="en")

    def literal(value: str) -> LiteralValue:
        return LiteralValue(lexical=value, datatype=XSD + "string")

    return NodeRecord(
        id="urn:c1:probe:keyword-" + uuid.uuid4().hex,
        types=[C1 + "Keyword"],
        properties={
            C1 + "keywordText": [literal(keyword.text)],
            C1 + "normalizedKeyword": [literal(keyword.normalized or "")],
            C1 + "normalizationVersion": [literal(keyword.normalization_version)],
            C1 + "keywordLanguage": [literal(keyword.language or "")],
        },
    )


async def _observations(case: LiveCase, start_id: str, target_id: str) -> dict[str, Any]:
    searches = {
        "label": {"label": {"text": "Ada Visible", "mode": "exact"}},
        "hidden_keyword": {"keywords_any": [{"text": "secret", "language": "en"}]},
        "relation": {"relations": [{"predicate": C1 + "worksFor", "target_id": target_id}]},
    }
    result: dict[str, Any] = {}
    for name, body in searches.items():
        response = await case.request("POST", "/v1/entities/search", actor="alice", json=body)
        assert response.status_code == 200, (name, response.text)
        payload = response.json()
        # New knowledge writes legitimately advance the public revision. The
        # selected content, count, explanation, and pagination must not change.
        result[name] = {
            key: payload[key]
            for key in ("items", "count", "explain", "indeterminate", "next_cursor")
        }
    path = "/v1/entities/" + quote(start_id, safe="") + "/neighborhood"
    neighborhood = await case.request(
        "GET", path, actor="alice", params={"predicates": C1 + "worksFor", "depth": 2}
    )
    assert neighborhood.status_code == 200, neighborhood.text
    payload = neighborhood.json()
    result["neighborhood"] = {
        key: payload[key] for key in ("nodes", "edges", "truncated", "budget", "next_cursor")
    }
    direct = await case.request("GET", "/v1/resources/" + quote(start_id, safe=""), actor="alice")
    assert direct.status_code == 200, direct.text
    result["direct_read"] = direct.json()
    return result


def test_t03_hidden_matching_entity_keyword_and_edges_are_noninterfering() -> None:
    async def run() -> None:
        async with live_case() as case:
            visible = await case.scope("M05-T03 visible")
            hidden = await case.scope("M05-T03 hidden")
            await case.grant(visible, "alice", "reader")
            # Synthetic records use the authenticated, test-only probe API;
            # both scopes and all bindings remain in the real security plane.
            start = entity_record(label="Ada Visible")
            target = entity_record(label="Visible Company")
            visible_edge = relation_record(start.id, target.id, (await case.principal("erin")).id)
            for record in (start, target, visible_edge):
                await case.provision(record, visible)

            before = await _observations(case, start.id, target.id)
            assert [item["id"] for item in before["label"]["items"]] == [start.id]
            assert before["hidden_keyword"]["items"] == []
            assert [edge["assertion_id"] for edge in before["neighborhood"]["edges"]] == [
                visible_edge.id
            ]

            hidden_keyword = _keyword("secret")
            hidden_entity = entity_record(label="Ada Visible")
            hidden_to_hidden = relation_record(
                start.id, hidden_entity.id, (await case.principal("erin")).id
            )
            hidden_between_visible = relation_record(
                start.id, target.id, (await case.principal("erin")).id
            )
            for record in (hidden_keyword, hidden_entity, hidden_to_hidden, hidden_between_visible):
                await case.provision(record, hidden)
            changed = start.model_copy(deep=True)
            changed.properties[C1 + "keyword"] = [hidden_keyword.id]
            response = await case.request(
                "PUT",
                "/v1/probe/resources/" + quote(start.id, safe=""),
                json={"record": changed.model_dump(mode="json")},
            )
            assert response.status_code == 200, response.text

            after = await _observations(case, start.id, target.id)
            assert after == before
            assert hidden_entity.id not in str(after)
            assert hidden_keyword.id not in str(after)
            assert hidden_to_hidden.id not in str(after)
            assert hidden_between_visible.id not in str(after)

    asyncio.run(run())
