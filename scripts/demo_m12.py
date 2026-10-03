"""M12 demonstration: the human Explorer over the same secured API, with no AI key.

Runs in headless Chromium against disposable repositories on the real stack:

1. Carol finds the shared Person without a workspace, prepares a source-backed
   assertion in forms and submits it; Dave reviews and applies it (A02).
2. Alice and Bob read the same scoped document and see different parts (A14).
3. Dave previews battery context anchored to Tesla without choosing a project (A15).
4. Carol and Bob preview the test-development, support and documentation-update
   contexts for an explicit software target (A18-A20), and Bob sees code excerpts
   labelled as excerpts (A21, A22).
5. Carol proposes widening Bob's draft; Frank and Erin find it in their
   security-operation lists and approve it in the browser; Carol applies it.

The JSON summary and screenshots go to docs/evidence/M12/demo/. No token,
password or session value is written.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import software_producer as sp  # noqa: E402
from tests.browser.harness import Person, browser, explorer_server, sign_in  # noqa: E402
from tests.integration.m03.conftest import LiveCase, live_case  # noqa: E402
from tests.integration.m06.conftest import install_scoped_document  # noqa: E402
from tests.integration.m07.conftest import install_batteries  # noqa: E402
from tests.integration.m11.conftest import (  # noqa: E402
    accept,
    draft_operations,
    fixture_check,
    propose,
)
from tests.integration.m12.conftest import PERSON, directory_case, grant  # noqa: E402
from tests.integration.m12.test_t01_parity import _browser_write  # noqa: E402
from tests.integration.software import _template, copy_of  # noqa: E402

OUT = ROOT / "docs/evidence/M12/demo"
AI_VARIABLES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "AZURE_OPENAI_API_KEY",
)
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"


async def shot(person: Person, name: str) -> str:
    path = OUT / f"{name}.png"
    await person.page.screenshot(path=str(path), full_page=True)
    return path.name


def context_query(body: dict[str, Any]) -> str:
    target = body.get("target", {})
    form = {
        "profile": f"{body['profile']}@{body['profile_version']}",
        "anchor_id": body["anchor"]["id"],
        "snapshots": "\n".join(target.get("snapshots", [])),
        "contracts": "\n".join(target.get("contracts", [])),
        "configurations": "\n".join(target.get("configurations", [])),
        "goal": body.get("goal", ""),
        "aspects": "\n".join(body.get("aspects", [])),
        "budget": str(body["budget"]["maximum"]),
    }
    return "/explorer/context?" + urlencode({k: v for k, v in form.items() if v})


async def preview(
    case: LiveCase, person: Person, body: dict[str, Any], name: str
) -> dict[str, Any]:
    api = await case.request("POST", "/v1/context", actor=person.name, json=body)
    await person.goto(context_query(body))
    outcome = await person.field("outcome")
    expected = api.json().get("outcome")
    if api.status_code != 200 or outcome != expected:
        raise RuntimeError(f"{name}: page outcome {outcome!r}, API {api.status_code} {expected!r}")
    return {"profile": body["profile"], "outcome": outcome, "screenshot": await shot(person, name)}


async def directory_step(summary: dict[str, Any]) -> None:
    async with directory_case() as (case, scopes):
        scope = scopes["dir-company-a"]
        await grant(case, scope, "carol", "creator", "contributor")
        await grant(case, scope, "dave", "reader", "reviewer")
        async with explorer_server(case), browser() as instance:
            carol = await sign_in(instance, "carol")
            dave = await sign_in(instance, "dave")
            await carol.goto("/explorer/entities")
            listed = await carol.page.locator("tr[data-entity]").count()
            await carol.goto("/explorer/resource?id=" + quote(PERSON, safe=""))
            changeset = await _browser_write(carol, dave, scope)
            summary["a02_reviewed_write"] = {
                "entities_listed_without_workspace": listed,
                "changeset": changeset,
                "state": await dave.field("state"),
                "author_screen": await shot(carol, "a02-carol-person"),
                "reviewer_screen": await shot(dave, "a02-dave-applied"),
            }


async def document_step(summary: dict[str, Any]) -> None:
    async with live_case() as case:
        await install_scoped_document(case)
        async with explorer_server(case), browser() as instance:
            views: dict[str, Any] = {}
            for name in ("alice", "bob"):
                person = await sign_in(instance, name)
                await person.goto("/explorer/document?id=" + quote(DOCUMENT, safe=""))
                views[name] = {
                    "parts": await person.page.locator("li[data-part]").count(),
                    "screenshot": await shot(person, f"a14-{name}-document"),
                }
            if views["alice"]["parts"] >= views["bob"]["parts"]:
                raise RuntimeError("Alice and Bob should see different document views")
            summary["a14_scoped_document"] = views


async def batteries_step(summary: dict[str, Any]) -> None:
    async with live_case() as case:
        loaded = await install_batteries(case)
        async with explorer_server(case), browser() as instance:
            dave = await sign_in(instance, "dave")
            query = urlencode(
                {
                    "profile": "graph-context@1",
                    "anchor_label": "Tesla",
                    "topics": "batteries",
                    "revision": loaded["revision"],
                }
            )
            await dave.goto("/explorer/context?" + query)
            summary["a15_cross_project_context"] = {
                "outcome": await dave.field("outcome"),
                "truncated": await dave.field("truncated"),
                "screenshot": await shot(dave, "a15-dave-context"),
            }


async def software_step(summary: dict[str, Any], template: Any) -> None:
    configuration = [sp.configuration_id("default")]
    a1b1 = {
        "snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")],
        "configurations": configuration,
    }
    a2b2 = {
        "snapshots": [sp.snapshot_id("a2"), sp.snapshot_id("b2")],
        "contracts": [sp.file_id("a2", "openapi.json")],
        "configurations": configuration,
    }
    budget = {"unit": "bytes", "maximum": 524288}
    async with copy_of(template) as case:
        async with explorer_server(case), browser() as instance:
            carol = await sign_in(instance, "carol")
            bob = await sign_in(instance, "bob")
            previews = [
                await preview(
                    case,
                    carol,
                    {
                        "profile": "test-development",
                        "profile_version": "1",
                        "anchor": {"id": sp.symbol_id("ledger", "`ledger.api`/create_invoice().")},
                        "target": a1b1,
                        "goal": "conformance",
                        "budget": budget,
                    },
                    "a18-carol-test-development",
                ),
                await preview(
                    case,
                    carol,
                    {
                        "profile": "support-documentation",
                        "profile_version": "1",
                        "anchor": {"id": sp.operation_id("ledger", "createInvoice")},
                        "target": a1b1,
                        "budget": budget,
                    },
                    "a19-carol-support-documentation",
                ),
                await preview(
                    case,
                    bob,
                    {
                        "profile": "documentation-update",
                        "profile_version": "1",
                        "anchor": {"id": sp.capability_id("invoice-creation")},
                        "target": a2b2,
                        "budget": budget,
                    },
                    "a20-bob-documentation-update",
                ),
            ]
            await bob.goto(
                "/explorer/software?" + urlencode({"snapshots": "\n".join(a2b2["snapshots"])})
            )
            labels = await bob.page.locator('[data-field="completeness"]').all_inner_texts()
            summary["a18_a22_software"] = {
                "previews": previews,
                "code_labels": sorted(set(labels)),
                "lookup_screenshot": await shot(bob, "a21-bob-lookup"),
            }

            # The draft widening as a browser workflow (A22 publication boundary).
            bob_id = (await case.principal("bob")).id
            operations, ids = draft_operations(
                template, bob_id, check=fixture_check(template), lineage=True
            )
            status, view = await propose(case, "bob", operations)
            if status != 200:
                raise RuntimeError(f"draft proposal failed: {status}")
            await accept(case, view, "dave")
            await carol.goto("/explorer/scopes")
            await carol.page.fill("#r-resource", ids["document"])
            await carol.page.fill("#r-scope", "sw-docs")
            async with carol.page.expect_navigation():
                await carol.page.get_by_role("button", name="Propose re-scope").click()
            states = [await carol.field("state")]
            for name in ("frank", "erin"):
                approver = await sign_in(instance, name)
                await approver.goto("/explorer/operations")
                await approver.page.locator("tr[data-operation] a").first.click()
                await approver.page.wait_for_load_state("load")
                async with approver.page.expect_navigation():
                    await approver.page.click('[data-action="approve"]')
                states.append(await approver.field("state"))
            await carol.page.reload()
            async with carol.page.expect_navigation():
                await carol.page.click('[data-action="apply"]')
            states.append(await carol.field("state"))
            summary["a22_reviewed_widening"] = {
                "states": states,
                "screenshot": await shot(carol, "a22-carol-applied"),
            }
            if states != ["proposed", "proposed", "approved", "applied"]:
                raise RuntimeError(f"unexpected widening states {states}")


def main() -> None:
    present = [name for name in AI_VARIABLES if os.environ.get(name)]
    if present:
        raise SystemExit("AI provider variables must be unset for the no-AI demonstration")
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"ai_provider_variables_set": present}
    asyncio.run(directory_step(summary))
    asyncio.run(document_step(summary))
    asyncio.run(batteries_step(summary))
    # The software template keeps its own event loop open while copies are made.
    for template in _template(None):
        asyncio.run(software_step(summary, template))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
