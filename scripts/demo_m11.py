"""M11 A20 demonstration on a disposable repository: update context, draft, widening, receipt.

Loads software-integration 1.3, asks `documentation-update` for capability
"Invoice creation" at {a2, b2, contract 1.1.0} as Bob, submits Bob's draft
with lineage into his drafting scope, widens it to `sw-docs` with the
destination admin (Frank) and the lineage admin (Erin), approves the draft,
and imports the publisher's report. No AI service or network fetch is
involved; the locator is inert text. Run with C1_STACK=1 from the repository root.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.m11.conftest import (  # noqa: E402
    accept,
    context,
    draft_operations,
    fixture_check,
    operation_step,
    propose,
    rescope,
    target,
    units,
    update,
)
from tests.integration.m11.test_t05_publication import _receipt  # noqa: E402
from tests.integration.software import CaseLoader, Template, load  # noqa: E402


def summary(package: dict[str, Any]) -> dict[str, Any]:
    a2 = sp.snapshot_id("a2")
    return {
        "revision": package["revision"],
        "document_structure": [
            {
                "document": unit.get("document_title") or unit["document"]["title"],
                "part": (unit.get("text") or "").strip()[:40],
                "a2": unit["applicability"][a2]["state"] if "applicability" in unit else None,
            }
            for unit in units(package, "document-structure")
        ],
        "responsibilities": [
            {"symbol": unit["symbol"]["label"], "responsibility": unit["responsibility"]}
            for unit in units(package, "responsibilities", "code-unit")
        ],
        "interface_contract": [
            unit.get("operation", {}).get("operation_id") or unit["kind"]
            for unit in units(package, "interface-contract")
        ],
        "changes": [
            (unit["kind"], unit.get("state"), unit.get("basis"))
            for unit in units(package, "changes")
        ],
        "drafts": [
            {
                "title": unit["title"],
                "state": unit["draft_state"],
                "publication": unit["publication_state"],
            }
            for unit in units(package, "drafts")
        ],
        "compatibility": [
            (unit["pair"], unit["status"]) for unit in units(package, "compatibility")
        ],
        "publication_statement": package["structured"]["publication"],
    }


async def main() -> None:
    async with live_case() as case:
        loaded = await load(case)
        template = Template(case=None, loaded=loaded)  # type: ignore[arg-type]
        bob = (await case.principal("bob")).id
        first = await context(case, "bob", update(target("a2", "b2")))
        check = fixture_check(template)
        operations, ids = draft_operations(template, bob, check=check)
        _, view = await propose(case, "bob", operations)
        await accept(case, view, "dave")
        proposal = await rescope(case, ids["document"], "sw-docs", "carol")
        states = [proposal["state"]]
        for approver in ("frank", "erin"):
            states.append(
                (await operation_step(case, proposal["id"], "approve", approver)).json()["state"]
            )
        applied = await operation_step(case, proposal["id"], "apply", "carol")
        approved, _ = draft_operations(template, bob, check=check, state="approved")
        record = next(op["record"] for op in approved if op["record"]["id"] == ids["draft"])
        _, view = await propose(
            case,
            "bob",
            [
                {
                    "kind": "replace",
                    "resource_id": ids["draft"],
                    "record": record,
                    "reason": "approve",
                }
            ],
        )
        await accept(case, view, "dave")
        before_receipt = await context(case, "bob", update(target("a2", "b2")))
        loader = CaseLoader(case)
        ci = loaded["principals"]["ci"]
        await loader.apply_changeset(
            sp.operations(_receipt(ids["draft"], ci, "sw-publications", "demo")),
            author="ci",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="admin"))["knowledge_revision"],
        )
        final = await context(case, "bob", update(target("a2", "b2")))
        alice = await case.request(
            "GET", "/v1/documents/by-id", params={"document_id": ids["document"]}, actor="alice"
        )
        print(
            json.dumps(
                {
                    "update_context_bob": summary(first),
                    "widening_states": states + [applied.json().get("state")],
                    "after_approval": summary(before_receipt)["drafts"],
                    "after_receipt": summary(final)["drafts"],
                    "alice_reads_widened_draft": alice.status_code,
                    "markdown_excerpt": first["markdown"][:1200],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
