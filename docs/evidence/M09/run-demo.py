"""M09 demonstration on an isolated, disposable repository (no AI, no network).

It loads software-integration v1.1 into a fresh knowledge database and
authorization store (the M03 live-case harness), requests the conformance
`test-development` package for `create_invoice` at {a1, b1, default} as
Carol, runs the external consumer (fail on a1, pass on a2), and repeats the
request to show the imported runs' labels. The development instance is not
touched. Run with C1_STACK=1 from the repository root.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts import demo_m09_consumer as consumer  # noqa: E402
from scripts import software_producer as sp  # noqa: E402
from tests.integration.m03.conftest import live_case  # noqa: E402
from tests.integration.software import CaseLoader, load  # noqa: E402

ANCHOR = sp.symbol_id("ledger", "`ledger.api`/create_invoice().")
TARGET = {
    "snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")],
    "configurations": [sp.configuration_id("default")],
}


async def package(case: Any) -> dict[str, Any]:
    response = await case.request(
        "POST",
        "/v1/context",
        actor="carol",
        json={
            "profile": "test-development",
            "profile_version": "1",
            "anchor": {"id": ANCHOR},
            "target": TARGET,
            "goal": "conformance",
            "budget": {"unit": "bytes", "maximum": 524288},
        },
    )
    response.raise_for_status()
    return dict(response.json())


def summary(value: dict[str, Any]) -> dict[str, Any]:
    sections = value["structured"]["sections"]
    return {
        "goal_statement": value["structured"]["goal_statement"],
        "normative": [
            (u["path"], u["commit"][:12], u["text"].strip()[:90]) for u in sections["normative"]
        ],
        "implementation": [
            (u["kind"], u["path"], u["code_completeness"], u["text"].splitlines()[0])
            for u in sections["implementation"]
        ],
        "tests": [
            (u["test_case"]["label"], u["status"], u["matching_results"]) for u in sections["tests"]
        ],
        "runs": [
            (
                u["result"],
                u["match"],
                u["integration_mode"],
                u["integration_evidence"],
                [s["label"] for s in u["snapshots"]],
                (u["configuration"] or {}).get("name"),
            )
            for u in sections["runs"]
        ],
        "instructions": [(u["path"], u["untrusted"]) for u in sections["instructions"]],
        "discrepancies": [
            sorted(c.get("quote", "") for c in u["citations"]) for u in sections["discrepancies"]
        ],
        "gaps": [gap["kind"] for gap in value["structured"]["gaps"]],
        "rendered_bytes": value["bounds"]["rendered_bytes"],
    }


async def main() -> None:
    async with live_case() as case:
        await load(case)
        before = await package(case)
        outcome = await consumer.consume(CaseLoader(case))
        after = await package(case)
        print(
            json.dumps(
                {
                    "before_consumer": summary(before),
                    "consumer": outcome,
                    "after_consumer_tests": summary(after)["tests"],
                    "after_consumer_runs": summary(after)["runs"],
                    "markdown_excerpt": before["markdown"][:1500],
                },
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
