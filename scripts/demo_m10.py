"""M10 two-request support demonstration (A19) on a disposable repository.

Loads software-integration into a fresh repository, asks `support-documentation`
for createInvoice at {a2, b2} with aspects [retry, timeout, configuration] as
Dave, then follows up explicitly with `support-implementation` for the missing
aspects using the returned token, and repeats the follow-up as Alice
(documentation-only). No AI service or network fetch is involved.
Run with C1_STACK=1 from the repository root.
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
from tests.integration.software import load  # noqa: E402

ANCHOR = sp.operation_id("ledger", "createInvoice")
TARGET = {
    "snapshots": [sp.snapshot_id("a2"), sp.snapshot_id("b2")],
    "configurations": [sp.configuration_id("default")],
}


def body(profile: str, aspects: list[str], token: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "profile": profile,
        "profile_version": "1",
        "anchor": {"id": ANCHOR},
        "target": TARGET,
        "aspects": aspects,
        "budget": {"unit": "bytes", "maximum": 524288},
    }
    if token:
        value["followup_token"] = token
    return value


def summary(value: dict[str, Any]) -> dict[str, Any]:
    structured = value["structured"]
    return {
        "revision": value["revision"],
        "sections": {
            name: [
                unit.get("document_title")
                or unit.get("document", {}).get("title")
                or (unit.get("symbol") or {}).get("label")
                or unit.get("kind")
                for unit in units
            ]
            for name, units in structured["sections"].items()
        },
        "missing_aspects": [item["aspect"]["label"] for item in structured["missing_aspects"]],
        "publication": structured["publication"],
    }


async def main() -> None:
    async with live_case() as case:
        await load(case)
        first = await case.request(
            "POST",
            "/v1/context",
            actor="dave",
            json=body("support-documentation", ["retry", "timeout", "configuration"]),
        )
        first.raise_for_status()
        documentation = first.json()
        token = documentation["followup"]["token"]
        aspects = [
            item["aspect"]["label"].lower() for item in documentation["followup"]["missing_aspects"]
        ]
        second = await case.request(
            "POST", "/v1/context", actor="dave", json=body("support-implementation", aspects, token)
        )
        second.raise_for_status()
        # Alice reads only sw-shared and cannot pin the target snapshots: both
        # stages give the uniform target not-found (owner decision, M10 report).
        alice = await case.request(
            "POST",
            "/v1/context",
            actor="alice",
            json=body("support-documentation", ["retry", "timeout", "configuration"]),
        )
        assert alice.status_code == 404, alice.text
        print(
            json.dumps(
                {
                    "documentation_stage_dave": summary(documentation),
                    "implementation_stage_dave": summary(second.json()),
                    "documentation_stage_alice": {
                        "status": alice.status_code,
                        "code": alice.json()["code"],
                    },
                    "markdown_excerpt": documentation["markdown"][:1200],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
