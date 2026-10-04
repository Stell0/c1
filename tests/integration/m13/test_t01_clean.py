"""M13-T01: a clean, AI-free reference deployment serves every workflow over TLS."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import quote, urlencode

from scripts import software_producer as sp
from scripts.demo_m07 import expected_actors
from tests.integration.m04.conftest import action, new_changeset
from tests.integration.m07.conftest import EXPECTED, canonical, package
from tests.integration.m10.conftest import documentation, implementation
from tests.integration.m10.conftest import target as support_target
from tests.integration.m11.conftest import target as update_target
from tests.integration.m11.conftest import update
from tests.integration.m12.conftest import PERSON, PHONE
from tests.integration.m13 import browser as rb
from tests.integration.m13 import reference as ref
from tests.integration.m13.conftest import Reference

ROOT = ref.ROOT
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"
C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _container_environments() -> dict[str, list[str]]:
    names = ref.engine(
        "ps",
        "--filter",
        f"label=com.docker.compose.project={ref.PROJECT}",
        "--format",
        "{{.Names}}",
    ).split()
    result = {}
    for name in names:
        env = json.loads(ref.engine("inspect", name, "--format", "{{json .Config.Env}}"))
        result[name] = [item.split("=", 1)[0] for item in env]
    return result


async def _all(case: ref.ReferenceCase, path: str, actor: str, key: str) -> list[Any]:
    """Every page of a list or export, following signed cursors."""
    items: list[Any] = []
    params: dict[str, str] = {"limit": "200"}
    for _ in range(200):
        response = await case.request("GET", path, actor=actor, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body[key].get("@graph", []) if key == "snapshot" else body[key])
        if not body.get("next_cursor"):
            return items
        params = {"limit": "200", "cursor": body["next_cursor"]}
    raise AssertionError("pagination did not finish")


def _mask_bytes(markdown: str) -> str:
    return re.sub(r"(?m)^- rendered\\_bytes: \d+$", "- rendered\\_bytes: <n>", markdown)


def test_t01_isolation_no_ai_and_published_ports(reference: Reference) -> None:
    for name, keys in _container_environments().items():
        assert not set(keys) & set(ref.AI_VARIABLES), name
    published = ref.engine(
        "ps",
        "--filter",
        f"label=com.docker.compose.project={ref.PROJECT}",
        "--format",
        "{{.Names}} {{.Ports}}",
    )
    with_ports = [line for line in published.splitlines() if "->" in line]
    assert len(with_ports) == 1 and "proxy" in with_ports[0] and "127.0.0.1:18443" in with_ports[0]
    probe = ref.engine(
        "exec",
        ref.container("c1"),
        "python",
        "-c",
        "import socket\n"
        "for h in [('1.1.1.1', 443), ('api.openai.com', 443)]:\n"
        "    try:\n"
        "        socket.create_connection(h, 5).close(); print('OPEN', h)\n"
        "    except OSError as e:\n"
        "        print('BLOCKED', h, type(e).__name__)\n",
    )
    assert "OPEN" not in probe and probe.count("BLOCKED") == 2, probe


def test_t01_api_workflows_documents_and_every_context_profile(reference: Reference) -> None:
    case = reference.case

    async def run() -> None:
        expected_assertions = json.loads(
            (ROOT / "fixtures/directory/expected/assertions.json").read_text()
        )
        expected_export = json.loads((ROOT / "fixtures/directory/expected/export.json").read_text())
        directory = {
            r["id"]
            for r in json.loads((ROOT / "fixtures/directory/fixture.json").read_text())["records"]
        }
        for principal in ("alice", "bob", "carol", "dave"):
            assertions = await _all(case, "/v1/assertions", principal, "items")
            found = sorted(i["id"] for i in assertions if i["id"] in directory)
            assert found == sorted(expected_assertions[principal]), principal
            graph = await _all(case, "/v1/export", principal, "snapshot")
            exported = sorted(i["@id"] for i in graph if i["@id"] in directory)
            assert exported == sorted(expected_export[principal]), principal

        # A reviewed write and its history through the public API.
        scopes = {
            item["label"]: item["id"]
            for item in (await case.request("GET", "/v1/access-scopes", actor="erin")).json()[
                "access_scopes"
            ]
        }
        company_a = scopes["Directory Company A"]
        await case.grant(company_a, "carol", "creator")
        await case.grant(company_a, "carol", "contributor")
        await case.grant(company_a, "dave", "reviewer")
        await case.grant(company_a, "dave", "reader")
        carol = (await case.principal("carol")).id
        record = {
            "id": f"urn:c1:instance:dev:assertion/{uuid.uuid4()}",
            "types": [C1 + "Assertion"],
            "properties": {
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject": [PERSON],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate": [PHONE],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [
                    {"lexical": "+1 555 0177", "datatype": XSD + "string"}
                ],
                C1 + "origin": [{"lexical": "manual", "datatype": XSD + "string"}],
                C1 + "reviewState": [{"lexical": "reported", "datatype": XSD + "string"}],
                C1 + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
                C1 + "manualStatement": [{"lexical": "true", "datatype": XSD + "boolean"}],
                "http://www.w3.org/ns/prov#wasAttributedTo": [carol],
            },
        }
        proposal = await new_changeset(
            case, [{"kind": "create", "record": record, "scope_id": company_a}], actor="carol"
        )
        state = (await action(case, proposal["id"], "submit", actor="carol"))["state"]
        if state == "submitted":
            state = (await action(case, proposal["id"], "validate", actor="carol"))["state"]
        assert state == "validated"
        assert (await action(case, proposal["id"], "approve", actor="dave"))["state"] == "approved"
        assert (await action(case, proposal["id"], "apply", actor="dave"))["state"] == "applied"
        history = await case.request(
            "GET", "/v1/history", actor="carol", params={"resource_id": record["id"]}
        )
        assert history.status_code == 200
        assert history.json()["items"][0]["changeset_id"] == proposal["id"]

        # Document reconstruction differs per reader, exactly as the M06 goldens.
        for principal in ("alice", "bob", "carol"):
            rendered = await case.request(
                "GET",
                f"/v1/documents/{quote(DOCUMENT, safe='')}/render",
                actor=principal,
                params={"revision": reference.scoped["revision2"], "format": "markdown"},
            )
            assert rendered.status_code == 200, rendered.text
            golden = (ROOT / f"fixtures/scoped-document/expected/{principal}.md").read_text()
            assert rendered.json()["content"] == golden.rstrip("\n")

        # Every context profile of the catalog.
        loaded = reference.batteries
        result = await package(case, loaded)
        assert result["outcome"] == "resolved"
        # The reviewed M07 golden, with deployment identities substituted. Only the
        # self-referential byte count is masked: it depends on the length of this
        # deployment's escaped principal IDs and revision, so it is checked as the
        # exact UTF-8 length of the package instead.
        markdown = result["markdown"]
        assert result["bounds"]["rendered_bytes"] == len(markdown.encode("utf-8"))
        golden = expected_actors(
            (EXPECTED / "context-dave.md").read_text(encoding="utf-8"),
            loaded["principals"],
            encode=False,
            markdown=True,
        )
        assert _mask_bytes(canonical(markdown, loaded["revision"])) == _mask_bytes(golden)
        test_dev = {
            "profile": "test-development",
            "profile_version": "1",
            "anchor": {"id": sp.symbol_id("ledger", "`ledger.api`/create_invoice().")},
            "target": {
                "snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")],
                "configurations": [sp.configuration_id("default")],
            },
            "goal": "conformance",
            "budget": {"unit": "bytes", "maximum": 524288},
        }
        outcomes: dict[str, Any] = {}
        for name, actor, body in (
            ("test-development", "carol", test_dev),
            ("support-documentation", "carol", documentation(support_target("a1", "b1"))),
            ("documentation-update", "bob", update(update_target("a2", "b2"))),
        ):
            response = await case.request("POST", "/v1/context", actor=actor, json=body)
            assert response.status_code == 200, (name, response.text[:400])
            outcomes[name] = response.json()
            assert outcomes[name]["outcome"] == "resolved", name
        followup = outcomes["support-documentation"].get("followup")
        aspects = [
            a["aspect"]["label"]
            for a in outcomes["support-documentation"]["structured"].get("missing_aspects", [])
        ]
        body = implementation(
            support_target("a1", "b1"),
            aspects or ["error handling"],
            token=followup["token"] if followup else None,
        )
        response = await case.request("POST", "/v1/context", actor="carol", json=body)
        assert response.status_code == 200, response.text[:400]
        assert response.json()["outcome"] in {"resolved", "unresolved"}

    reference.run(run())


def test_t01_browser_flows_over_tls(reference: Reference) -> None:
    case = reference.case
    passwords = reference.identities["users"]

    async def run() -> None:
        scopes = {
            item["label"]: item["id"]
            for item in (await case.request("GET", "/v1/access-scopes", actor="erin")).json()[
                "access_scopes"
            ]
        }
        company_a = scopes["Directory Company A"]
        carol_id = (await case.principal("carol")).id
        record = {
            "id": f"urn:c1:instance:dev:assertion/{uuid.uuid4()}",
            "types": [C1 + "Assertion"],
            "properties": {
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject": [PERSON],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate": [PHONE],
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [
                    {"lexical": "+1 555 0188", "datatype": XSD + "string"}
                ],
                C1 + "origin": [{"lexical": "manual", "datatype": XSD + "string"}],
                C1 + "reviewState": [{"lexical": "reported", "datatype": XSD + "string"}],
                C1 + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
                C1 + "manualStatement": [{"lexical": "true", "datatype": XSD + "boolean"}],
                "http://www.w3.org/ns/prov#wasAttributedTo": [carol_id],
            },
        }
        proposal = await new_changeset(
            case, [{"kind": "create", "record": record, "scope_id": company_a}], actor="carol"
        )
        state = (await action(case, proposal["id"], "submit", actor="carol"))["state"]
        if state == "submitted":
            await action(case, proposal["id"], "validate", actor="carol")
        async with rb.browser() as instance:
            carol = await rb.sign_in(instance, "carol", passwords["carol"])
            await carol.page.goto(ref.BASE + "/explorer/entities")
            assert await carol.page.locator("tr[data-entity]").count() > 0
            query = urlencode(
                {
                    "profile": "graph-context@1",
                    "anchor_label": "Tesla",
                    "topics": "batteries",
                    "revision": reference.batteries["revision"],
                }
            )
            await carol.page.goto(ref.BASE + "/explorer/context?" + query)
            assert (await carol.page.locator('[data-field="outcome"]').inner_text()) == "resolved"
            dave = await rb.sign_in(instance, "dave", passwords["dave"])
            await dave.page.goto(ref.BASE + "/explorer/changeset?id=" + quote(proposal["id"]))
            async with dave.page.expect_navigation():
                await dave.page.click('[data-action="approve"]')
            async with dave.page.expect_navigation():
                await dave.page.click('[data-action="apply"]')
            assert (await dave.page.locator('[data-field="state"]').inner_text()) == "applied"
            headers = [r.headers for r in dave.recorder.responses if r.url.startswith(ref.BASE)]
            assert headers and all(
                h.get("content-security-policy", "").startswith("default-src 'none'")
                for h in headers
                if "text/html" in h.get("content-type", "")
            )

    reference.run(run())
