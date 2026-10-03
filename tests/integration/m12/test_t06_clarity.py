"""M12-T06: pages state revision, filters, target, conflicts and bounds as the API does."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from urllib.parse import urlencode

import pytest

from scripts import software_producer as sp
from tests.browser.harness import Person, browser, browser_enabled, explorer_server, sign_in
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m04.conftest import action, new_changeset
from tests.integration.m07.conftest import install_batteries, request_body
from tests.integration.m11.conftest import target, update
from tests.integration.m12.conftest import PERSON, PHONE, directory_case, grant
from tests.integration.software import Template, copy_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
TRUTH_WORDS = ("verified", "true claim", "proven", "fact-checked")


def _claim(value: str, attributed: str, *, confidence: str | None = None) -> dict[str, Any]:
    def lit(text: str, datatype: str = XSD + "string") -> dict[str, str]:
        return {"lexical": text, "datatype": datatype}

    properties: dict[str, Any] = {
        RDF + "subject": [PERSON],
        RDF + "predicate": [PHONE],
        RDF + "object": [lit(value)],
        C1 + "origin": [lit("manual")],
        C1 + "reviewState": [lit("reported")],
        C1 + "lifecycle": [lit("active")],
        C1 + "manualStatement": [lit("true", XSD + "boolean")],
        "http://www.w3.org/ns/prov#wasAttributedTo": [attributed],
    }
    if confidence is not None:
        properties[C1 + "confidence"] = [lit(confidence, XSD + "decimal")]
    return {
        "id": f"urn:c1:instance:dev:assertion/{uuid.uuid4()}",
        "types": [C1 + "Assertion"],
        "properties": properties,
    }


async def _apply(case: LiveCase, operations: list[dict[str, Any]], author: str) -> None:
    proposal = await new_changeset(case, operations, actor=author)
    state = (await action(case, proposal["id"], "submit", actor=author))["state"]
    if state == "submitted":
        state = (await action(case, proposal["id"], "validate", actor=author))["state"]
    assert state == "validated", state
    assert (await action(case, proposal["id"], "approve", actor="dave"))["state"] == "approved"
    assert (await action(case, proposal["id"], "apply", actor="dave"))["state"] == "applied"


def _no_truth_language(text: str) -> None:
    lowered = text.lower()
    for word in TRUTH_WORDS:
        assert word not in lowered, word


async def _directory(person: Person, case: LiveCase, values: list[str]) -> None:
    filters = {"label": "Company", "label_mode": "prefix", "order": "label"}
    await person.goto("/explorer/entities?" + urlencode(filters))
    api = await case.request("GET", "/v1/entities", actor="carol", params=filters)
    body = api.json()
    instance = (await case.request("GET", "/v1/instance", actor="carol")).json()
    assert await person.field("instance") == instance["instance_id"] == body["instance"]
    assert await person.field("revision") == body["revision"]
    assert await person.field("count") == str(body["count"])
    assert await person.field("order") == body["order"] == "label"
    active = await person.field("filters")
    assert "label=Company" in active and "order" not in active.split(";")[0].split("=")[0]

    await person.goto("/explorer/competing?" + urlencode({"subject": PERSON, "predicate": PHONE}))
    competing = await case.request(
        "GET", "/v1/assertions", actor="carol", params={"competing_for": f"{PERSON},{PHONE}"}
    )
    claims = competing.json()["items"]
    assert len(claims) >= 2
    assert await person.page.locator("[data-claim]").count() == len(claims)
    text = await person.page.inner_text("main")
    for value in values:
        assert value in text
    assert "reported (not reviewed)" in text
    assert "uncalibrated confidence, not a probability" in text
    _no_truth_language(text)


def test_t06_pages_match_the_api_and_never_imply_verified_truth(
    software_template: Template,
) -> None:
    async def run() -> None:
        async with directory_case() as (case, scopes):
            scope = scopes["dir-company-a"]
            await grant(case, scope, "carol", "creator", "contributor", "reader")
            await grant(case, scope, "dave", "reader", "reviewer")
            carol_id = (await case.principal("carol")).id
            values = ["+1 555 0101", "+1 555 0102"]
            await _apply(
                case,
                [
                    {"kind": "create", "record": _claim(values[0], carol_id), "scope_id": scope},
                    {
                        "kind": "create",
                        "record": _claim(values[1], carol_id, confidence="0.7"),
                        "scope_id": scope,
                    },
                ],
                "carol",
            )
            async with explorer_server(case), browser() as instance:
                carol = await sign_in(instance, "carol")
                await _directory(carol, case, values)

        async with live_case() as case:
            loaded = await install_batteries(case)
            async with explorer_server(case), browser() as instance:
                dave = await sign_in(instance, "dave")
                body = request_body(loaded, fields=["capacity", "cycle_life"])
                page_one = None
                for budget in (4096, 6144, 8192, 12288, 16384, 24576):
                    response = await case.request(
                        "POST",
                        "/v1/context",
                        actor="dave",
                        json={**body, "budget": {"unit": "bytes", "maximum": budget}},
                    )
                    if response.status_code == 200 and response.json()["bounds"]["truncated"]:
                        page_one = response.json()
                        break
                assert page_one is not None
                form = {
                    "profile": "graph-context@1",
                    "anchor_label": "Tesla",
                    "topics": "batteries",
                    "fields": "capacity\ncycle_life",
                    "revision": loaded["revision"],
                    "budget": str(budget),
                }
                await dave.goto("/explorer/context?" + urlencode(form))
                bounds = page_one["bounds"]
                assert await dave.field("revision") == page_one["revision"]
                assert await dave.field("truncated") == "yes"
                assert await dave.field("included_units") == str(bounds["included_units"])
                assert await dave.field("deferred_units") == str(bounds["deferred_units"])
                assert await dave.field("bytes") == (
                    f"{bounds['rendered_bytes']} / {bounds['maximum']}"
                )
                if "not present in the returned material" in page_one["markdown"]:
                    assert "not present in the returned material" in await dave.page.inner_text(
                        "main"
                    )
                markdown = await dave.page.inner_text('pre[aria-label="Context Markdown"]')
                assert markdown == page_one["markdown"].rstrip("\n") or (
                    markdown.rstrip("\n") == page_one["markdown"].rstrip("\n")
                )
                href = await dave.page.get_attribute('[data-field="continuation"]', "href")
                assert href
                await dave.goto(href)
                second = await case.request(
                    "POST",
                    "/v1/context",
                    actor="dave",
                    json={
                        **body,
                        "budget": {"unit": "bytes", "maximum": budget},
                        "cursor": bounds["next_cursor"],
                    },
                )
                assert second.status_code == 200, second.text
                assert await dave.field("included_units") == str(
                    second.json()["bounds"]["included_units"]
                )
                _no_truth_language(await dave.page.inner_text("main"))

        async with copy_of(software_template) as case:
            async with explorer_server(case), browser() as instance:
                bob = await sign_in(instance, "bob")
                spec = target("a2", "b2")
                body = update(spec)
                api = await case.request("POST", "/v1/context", actor="bob", json=body)
                assert api.status_code == 200, api.text
                package = api.json()
                form = {
                    "profile": "documentation-update@1",
                    "anchor_id": body["anchor"]["id"],
                    "snapshots": "\n".join(spec["snapshots"]),
                    "contracts": "\n".join(spec["contracts"]),
                    "configurations": "\n".join(spec["configurations"]),
                    "budget": str(body["budget"]["maximum"]),
                }
                await bob.goto("/explorer/context?" + urlencode(form))
                region = await bob.page.inner_text('[data-region="target"]')
                api_target = json.dumps(package["structured"]["target"])
                for snapshot in spec["snapshots"]:
                    assert snapshot in region and snapshot in api_target
                for contract in spec["contracts"]:
                    assert contract in region
                structured = await bob.page.inner_text('[data-region="structured"]')
                assert "needs-review" in structured and "unknown" in structured
                assert ("needs-review" in json.dumps(package["structured"])) and (
                    "unknown" in json.dumps(package["structured"])
                )
                assert await bob.field("truncated") == (
                    "yes" if package["bounds"]["truncated"] else "no"
                )

                # Partial code is labelled as an excerpt, exactly as the API labels it.
                lookup_body = {"target": {"snapshots": spec["snapshots"]}, "limit": 50}
                lookup = await case.request(
                    "POST", "/v1/software/lookup", actor="bob", json=lookup_body
                )
                items = lookup.json()["items"]
                expected = [i["citation"]["code_completeness"] for i in items if i.get("citation")]
                assert "excerpt" in expected
                await bob.goto(
                    "/explorer/software?" + urlencode({"snapshots": "\n".join(spec["snapshots"])})
                )
                shown = await bob.page.locator('[data-field="completeness"]').all_inner_texts()
                assert shown == expected
                _no_truth_language(await bob.page.inner_text("main"))
                assert sp.snapshot_id("a2") in await bob.page.inner_text('[data-region="target"]')

    asyncio.run(run())
