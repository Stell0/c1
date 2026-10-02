"""M10-T05: a documentation-only principal gains no code access or existence signal.

Owner decision (2026-10-02): Alice cannot read the target snapshots, which live in
repository scopes, so both stages answer with the uniform target not-found. The test
proves that answer is identical across a perturbed copy and equals the answer for a
snapshot that does not exist (plan D9's "missing aspects" premise does not hold).
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m10.conftest import (
    context,
    documentation,
    implementation,
    section,
    target,
)
from tests.integration.software import CaseLoader, Template, copy_of


def test_t05_no_privilege_escalation(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as plain, copy_of(software_template) as perturbed:
            body = implementation(target("a2", "b2"), ["retry"])
            docs = documentation(target("a2", "b2"), ["retry"])
            ghost = target("a2", "b2")
            ghost["snapshots"] = [sp.ident("snapshot/none", "snapshot"), ghost["snapshots"][1]]
            nowhere = implementation(ghost, ["retry"])
            alice = {
                "implementation": await context(plain, "alice", body, status=404),
                "documentation": await context(plain, "alice", docs, status=404),
                "unknown": await context(plain, "alice", nowhere, status=404),
            }
            assert alice["implementation"] == alice["documentation"] == alice["unknown"]
            assert alice["implementation"]["code"] == "C1-SW-404"

            # Hidden code that addresses the same aspect changes nothing for Alice.
            planner = sp.Planner(sp.load_inputs(), software_template.loaded["principals"])
            planner.runs()
            symbol = sp.symbol_id("ledger", "`ledger.api`/get_invoice().")
            part = planner._definition_part("a2", "ledger", "`ledger.api`/get_invoice().")
            assert part is not None
            extra = sp.Run(
                "m10-extra",
                "analyzer",
                "review-notes",
                "a2",
                sp.activity_record(
                    "m10-extra", planner.principals["analyzer"], "review-notes", [], "sw-ledger"
                ),
            )
            extra.add(extra.activity)
            sp.claim_with_evidence(
                extra,
                "m10-extra/get-invoice-retry",
                symbol,
                sp.S + "addressesAspect",
                sp.aspect_id("retry"),
                scope="sw-ledger",
                principal=planner.principals["analyzer"],
                target=part,
                revision=planner.commit("a2"),
                origin="derived",
            )
            await sp.apply_run(CaseLoader(perturbed), extra, skip_complete=False)
            dave = await context(perturbed, "dave", body)
            assert "ledger.api.get_invoice" in {
                u["symbol"]["label"] for u in section(dave, "implementation") if "symbol" in u
            }
            assert await context(perturbed, "alice", body, status=404) == alice["implementation"]
            assert await context(perturbed, "alice", docs, status=404) == alice["documentation"]

            # Citation expansion of a code part is the uniform not-found answer.
            hidden = await plain.request(
                "GET", "/v1/resources/" + quote(part, safe=""), actor="alice"
            )
            unknown = await plain.request(
                "GET",
                "/v1/resources/" + quote(sp.ident("part/none", "part"), safe=""),
                actor="alice",
            )
            assert hidden.status_code == unknown.status_code == 404
            assert hidden.json() == unknown.json()

    asyncio.run(run())
