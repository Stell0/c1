"""M12-T03: hidden documents, relations and code never reach the browser.

Every page Alice or Dave receives is compared, byte for byte after removing
only per-session and per-repository values, with the same page from a twin
repository in which the hidden records were never written.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from urllib.parse import quote, urlencode

import pytest

from scripts import software_producer as sp
from tests.browser.harness import Person, browser, browser_enabled, explorer_server, sign_in
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m06.conftest import (
    _apply_as_service,
    _service_token,
    fixture_spec,
    install_scoped_document,
)
from tests.integration.m11.conftest import target, update
from tests.integration.software import Template, copy_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"
NOTES = "urn:c1:instance:dev:document/00000062-0000-4000-8000-000000000000"
HIDDEN_PARTS = {
    f"urn:c1:instance:dev:document-part/0000007{n}-0000-4000-8000-000000000000"
    for n in (3, 4, 5, 6)
}
RELATION_SENTINEL = "m12-hidden-relation-" + uuid.uuid4().hex
RESTRICTED_TEXT = "Restricted pricing rules"
_VOLATILE = (
    (re.compile(r'name="csrf" value="[^"]+"'), 'name="csrf" value="<csrf>"'),
    (re.compile(r"(branch|commit):[A-Za-z0-9_-]+"), "<revision>"),
    (re.compile(r"m03_[0-9a-f]{32}"), "<instance>"),
    (re.compile(r"changeset-[0-9a-f]{32}"), "<changeset>"),
    (re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)"), "<recorded>"),
    (re.compile(r"(cursor|followup_token)=[A-Za-z0-9._~%-]+"), r"\1=<token>"),
)


def normalized(html: str) -> str:
    for pattern, replacement in _VOLATILE:
        html = pattern.sub(replacement, html)
    return html


async def _pages(person: Person, paths: list[str]) -> dict[str, tuple[int, str]]:
    result = {}
    for path in paths:
        response = await person.goto(path)
        assert response is not None
        result[path] = (response.status, normalized(await response.text()))
    await person.recorder.settle()
    return result


async def _hidden_relation(case: LiveCase) -> None:
    """A relation between two documents Alice can read, bound where she cannot read."""
    token = await _service_token(case)
    service = (await case.validator.authenticate(token)).id
    scopes = {
        item["label"]: item["id"]
        for item in (await case.request("GET", "/v1/access-scopes", actor="erin")).json()[
            "access_scopes"
        ]
    }
    legal = next(scope for label, scope in scopes.items() if "legal" in label)
    record = {
        "id": f"urn:c1:instance:dev:assertion/{RELATION_SENTINEL}",
        "types": [C1 + "Assertion"],
        "properties": {
            RDF + "subject": [DOCUMENT],
            RDF + "predicate": [C1 + "worksFor"],
            RDF + "object": [NOTES],
            C1 + "origin": [{"lexical": "manual", "datatype": XSD + "string"}],
            C1 + "reviewState": [{"lexical": "reported", "datatype": XSD + "string"}],
            C1 + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
            C1 + "manualStatement": [{"lexical": "true", "datatype": XSD + "boolean"}],
            "http://www.w3.org/ns/prov#wasAttributedTo": [service],
        },
    }
    await _apply_as_service(
        case, token, [{"kind": "create", "record": record, "scope_id": legal}], "Hidden relation"
    )


def _document_paths() -> list[str]:
    doc = quote(DOCUMENT, safe="")
    return [
        "/explorer/document?id=" + doc,
        "/explorer/document/source?" + urlencode({"id": DOCUMENT, "format": "markdown"}),
        "/explorer/document/source?" + urlencode({"id": DOCUMENT, "format": "text"}),
        "/explorer/documents",
        "/explorer/documents?" + urlencode({"text_contains": "e"}),
        "/explorer/resource?id=" + doc,
        "/explorer/resource?id=" + quote(NOTES, safe=""),
        "/explorer/document/history?id=" + doc,
    ]


def _software_paths() -> list[str]:
    spec = target("a2", "b2")
    lookup = {
        "snapshots": "\n".join([sp.snapshot_id("a1"), sp.snapshot_id("b1")]),
    }
    body = update(spec)
    context = {
        "profile": "documentation-update@1",
        "anchor_id": body["anchor"]["id"],
        "snapshots": "\n".join(spec["snapshots"]),
        "contracts": "\n".join(spec["contracts"]),
        "configurations": "\n".join(spec["configurations"]),
        "budget": str(body["budget"]["maximum"]),
    }
    return [
        "/explorer/software?" + urlencode(lookup),
        "/explorer/context?" + urlencode(context),
    ]


def test_t03_hidden_data_never_reaches_the_browser(
    software_template: Template, software_twin_template: Template
) -> None:
    async def run() -> None:
        fixture = fixture_spec()
        hidden_texts = [
            value["lexical"]
            for item in fixture["revision1"]
            if item["id"] in HIDDEN_PARTS
            for value in item["properties"].get(C1 + "text", [])
        ]
        assert hidden_texts
        observed: dict[str, dict[str, dict[str, tuple[int, str]]]] = {}
        for name, omit in (("real", False), ("twin", True)):
            async with live_case() as case:
                await install_scoped_document(case, omit_hidden_parts=omit)
                if not omit:
                    await _hidden_relation(case)
                async with explorer_server(case), browser() as instance:
                    alice = await sign_in(instance, "alice")
                    observed.setdefault(name, {})["documents"] = await _pages(
                        alice, _document_paths()
                    )
                    if name == "real":
                        everything = alice.recorder.everything()
                        for text in hidden_texts:
                            assert text not in everything, text
                        assert RELATION_SENTINEL not in everything
                        cookies = repr(await alice.context.cookies())
                        assert RELATION_SENTINEL not in cookies
        for name, template in (("real", software_template), ("twin", software_twin_template)):
            async with copy_of(template) as case:
                async with explorer_server(case), browser() as instance:
                    dave = await sign_in(instance, "dave")
                    observed[name]["software"] = await _pages(dave, _software_paths())
                    if name == "real":
                        assert RESTRICTED_TEXT not in dave.recorder.everything()
        for group in ("documents", "software"):
            for path, (status, html) in observed["real"][group].items():
                twin_status, twin_html = observed["twin"][group][path]
                assert status == twin_status, (path, status, twin_status)
                assert html == twin_html, path
        # The comparison is not vacuous: the pages carry real content.
        assert "Welcome to the Handbook" in observed["real"]["documents"][_document_paths()[0]][1]
        assert all(status == 200 for status, _ in observed["real"]["software"].values())

    asyncio.run(run())
