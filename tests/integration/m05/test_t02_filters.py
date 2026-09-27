"""M05-T02: combined filters and lexical/temporal behavior on real services."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from c1.model.keywords import Keyword
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import AssertionRecord, EntityRecord
from tests.integration.m04.conftest import (
    C1,
    XSD,
    LiveCase,
    live_case,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("C1_STACK") != "1", reason="M05 real services required"),
]

TIME = "http://www.w3.org/2006/time#"
RDF_LANG = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"


def _id(kind: str) -> str:
    return f"urn:c1:probe:{kind}-{uuid.uuid4().hex}"


def _string(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + "string")


def _keyword(text: str, language: str) -> NodeRecord:
    value = Keyword(text=text, language=language)
    properties: dict[str, list[str | LiteralValue]] = {
        C1 + "keywordText": [_string(value.text)],
        C1 + "normalizedKeyword": [_string(value.normalized or "")],
        C1 + "normalizationVersion": [_string(value.normalization_version)],
        C1 + "keywordLanguage": [_string(value.language or "")],
    }
    return NodeRecord(
        id=_id("keyword"),
        types=[C1 + "Keyword"],
        properties=properties,
    )


def _boundary(state: str, year: str | None = None) -> NodeRecord:
    properties: dict[str, list[str | LiteralValue]] = {C1 + "boundaryState": [_string(state)]}
    if year is not None:
        properties[TIME + "inXSDgYear"] = [LiteralValue(lexical=year, datatype=XSD + "gYear")]
    return NodeRecord(
        id=_id("boundary"),
        types=[C1 + "TimeBoundary"],
        properties=properties,
    )


def _ids(payload: dict[str, Any]) -> list[str]:
    return [item["id"] for item in payload["items"]]


async def _search(case: LiveCase, body: dict[str, Any]) -> dict[str, Any]:
    response = await case.request("POST", "/v1/entities/search", actor="alice", json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert isinstance(value, dict)
    return value


def test_t02_combined_filters_keyword_language_valid_time_and_recorded_order() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await case.scope("M05-T02 filters")
            await case.grant(scope, "alice", "reader")
            actor = (await case.principal("erin")).id
            en_energy = _keyword("  EnErGy  ", "en")
            en_battery = _keyword("battery", "en")
            company = EntityRecord(
                id=_id("entity"),
                labels=[LiteralValue(lexical="Example Company", datatype=RDF_LANG, language="en")],
            ).to_node()
            target = EntityRecord(
                id=_id("entity"),
                labels=[LiteralValue(lexical="Battery Pack v1", datatype=RDF_LANG, language="en")],
                keywords=[en_energy.id, en_battery.id],
            ).to_node()
            unknown = EntityRecord(
                id=_id("entity"),
                labels=[LiteralValue(lexical="Battery Pack v2", datatype=RDF_LANG, language="en")],
            ).to_node()
            start = _boundary("known", "2020Z")
            interval = NodeRecord(
                id=_id("interval"),
                types=[C1 + "TimeInterval"],
                properties={TIME + "hasBeginning": [start.id]},
            )
            revenue = AssertionRecord(
                id=_id("assertion"),
                subject=target.id,
                predicate=C1 + "revenue",
                object=LiteralValue(lexical="42.5000", datatype=XSD + "decimal"),
                origin="manual",
                manual_statement=True,
                attributed_to=actor,
                valid_interval=interval.id,
            ).to_node()
            relation = AssertionRecord(
                id=_id("assertion"),
                subject=target.id,
                predicate=C1 + "worksFor",
                object=company.id,
                origin="manual",
                manual_statement=True,
                attributed_to=actor,
                valid_interval=interval.id,
            ).to_node()
            unknown_claim = AssertionRecord(
                id=_id("assertion"),
                subject=unknown.id,
                predicate=C1 + "revenue",
                object=LiteralValue(lexical="50", datatype=XSD + "decimal"),
                origin="manual",
                manual_statement=True,
                attributed_to=actor,
            ).to_node()
            records = (
                en_energy,
                en_battery,
                company,
                target,
                unknown,
                start,
                interval,
                revenue,
                relation,
                unknown_claim,
            )
            for record in records:
                await case.provision(record, scope)
            revision = await case.knowledge.head()

            combined = await _search(
                case,
                {
                    "types": [C1 + "Entity"],
                    "label": {"text": "BATTERY PACK", "mode": "prefix", "language": "en"},
                    "keywords_all": [
                        {"text": "energy", "language": "en"},
                        {"text": "BATTERY", "language": "en"},
                    ],
                    "properties": [
                        {
                            "predicate": C1 + "revenue",
                            "op": "ge",
                            "value": {"lexical": "40", "datatype": XSD + "decimal"},
                        }
                    ],
                    "relations": [{"predicate": C1 + "worksFor", "target_id": company.id}],
                    "valid_at": "2020-06-01T00:00:00Z",
                    "revision": revision,
                    "order": "id",
                },
            )
            assert _ids(combined) == [target.id]
            assert combined["count"] == 1
            assert set(combined["explain"][target.id]) >= {
                "types",
                "label",
                "keywords_all",
                "properties",
                "relations",
                "valid_at",
            }
            assert (
                _ids(
                    await _search(
                        case,
                        {
                            "ids": [target.id],
                            "keywords_any": [{"text": "energy", "language": "de"}],
                        },
                    )
                )
                == []
            )
            assert _ids(
                await _search(
                    case, {"ids": [target.id, unknown.id], "valid_at": "2020-06-01T00:00:00Z"}
                )
            ) == [target.id]
            with_unknown = await _search(
                case,
                {
                    "ids": [target.id, unknown.id],
                    "valid_at": "2020-06-01T00:00:00Z",
                    "include_unknown": True,
                },
            )
            assert set(_ids(with_unknown)) == {target.id, unknown.id}
            assert with_unknown["indeterminate"] == [{"id": unknown.id, "rule": "unknown_validity"}]
            recorded = await _search(
                case, {"ids": [target.id, unknown.id], "order": "recorded", "revision": revision}
            )
            assert set(_ids(recorded)) == {target.id, unknown.id}
            assert recorded["revision"] == revision

    asyncio.run(run())


def test_t02_hidden_boundary_does_not_become_unbounded() -> None:
    async def run() -> None:
        async with live_case() as case:
            shared = await case.scope("M05-T02 hidden temporal bound")
            private = await case.scope("M05-T02 private temporal bound")
            await case.grant(shared, "alice", "reader")
            await case.grant(private, "frank", "access_admin")
            subject = EntityRecord(id=_id("entity"), labels=[_string("Temporal subject")]).to_node()
            start = _boundary("known", "2020Z")
            interval = NodeRecord(
                id=_id("interval"),
                types=[C1 + "TimeInterval"],
                properties={TIME + "hasBeginning": [start.id]},
            )
            claim = AssertionRecord(
                id=_id("assertion"),
                subject=subject.id,
                predicate=C1 + "revenue",
                object=LiteralValue(lexical="1", datatype=XSD + "decimal"),
                origin="manual",
                manual_statement=True,
                attributed_to=(await case.principal("erin")).id,
                valid_interval=interval.id,
            ).to_node()
            for record in (subject, start, interval, claim):
                await case.provision(record, shared)
            params = {
                "subject": subject.id,
                "valid_at": "2019-01-01T00:00:00Z",
            }
            before = await case.request("GET", "/v1/assertions", actor="alice", params=params)
            assert before.status_code == 200 and before.json()["count"] == 0, before.text

            proposed = await case.request(
                "POST", f"/v1/access-scopes/{private}/bindings", json={"resource_id": start.id}
            )
            assert proposed.status_code == 200, proposed.text
            operation = proposed.json()
            approved = await case.request(
                "POST", f"/v1/security-operations/{operation['id']}/approve", actor="frank"
            )
            assert approved.status_code == 200, approved.text
            applied = await case.request("POST", f"/v1/security-operations/{operation['id']}/apply")
            assert applied.status_code == 200, applied.text

            after = await case.request("GET", "/v1/assertions", actor="alice", params=params)
            assert after.status_code == 200 and after.json()["count"] == 0, after.text
            unknown = await case.request(
                "GET", "/v1/assertions", actor="alice", params={**params, "include_unknown": "true"}
            )
            assert unknown.status_code == 200, unknown.text
            assert unknown.json()["count"] == 1
            assert unknown.json()["indeterminate"] == [{"id": claim.id, "rule": "unknown_validity"}]

    asyncio.run(run())
