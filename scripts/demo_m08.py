"""M08 demonstration: pinned software targets over the software-integration fixture.

Prints the resolved target {a1, b1}, pinned citations for `submit_order` and
`create_invoice`, each relationship with its basis, and b1 coverage as seen by
Carol and by Dave (restricted source absent for Dave).
Run after `scripts/software_producer.py --fixture software-integration`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import software_producer as sp  # noqa: E402
from scripts.load_fixture import Loader, api_client  # noqa: E402

S = "urn:c1:ns:software#"


async def lookup(loader: Loader, actor: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = await loader.request("POST", "/v1/software/lookup", actor=actor, json_body=body)
    items.extend(page["items"])
    while page["next_cursor"]:
        page = await loader.request(
            "POST",
            "/v1/software/lookup",
            actor=actor,
            json_body={**body, "cursor": page["next_cursor"]},
        )
        items.extend(page["items"])
    return items


async def demonstrate() -> dict[str, Any]:
    async with api_client() as client:
        loader = await Loader.connect(client)
        target = {"snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")]}
        resolved = await loader.request(
            "POST", "/v1/software/targets/resolve", actor="reviewer", json_body=target
        )
        operation = sp.operation_id("ledger", "createInvoice")
        items = await lookup(
            loader,
            "reviewer",
            {"target": target, "select": {"operation_id": operation}, "limit": 200},
        )
        citations = [
            {
                "symbol": item["symbol"]["label"],
                "roles": item["roles"],
                "path": item["citation"]["path"],
                "commit": item["citation"]["commit"][:12],
                "line": item["range"]["start_line"] + 1,
                "completeness": item["citation"].get("code_completeness"),
            }
            for item in items
            if item["kind"] == "occurrence" and "definition" in item["roles"]
        ]
        relationships = sorted(
            (item["predicate"].split("#")[-1], item["basis"], item["origin"])
            for item in items
            if item["kind"] == "relationship"
        )
        coverage = {}
        for actor, name in (("reviewer", "carol"), ("dave", "dave")):
            found = await lookup(
                loader,
                actor,
                {
                    "target": {"snapshots": [sp.snapshot_id("b1")]},
                    "kinds": ["coverage"],
                    "limit": 200,
                },
            )
            coverage[name] = sorted(
                (item["method"], item["state"], tuple(item["analyzed"])) for item in found
            )
        return {
            "target": resolved["target"],
            "definitions": citations,
            "relationships": relationships,
            "coverage_b1": coverage,
        }


def main() -> None:
    print(json.dumps(asyncio.run(demonstrate()), indent=2, default=list))


if __name__ == "__main__":
    main()
