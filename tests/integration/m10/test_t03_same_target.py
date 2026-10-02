"""M10-T03: the follow-up keeps the first request's target and revision."""

from __future__ import annotations

import asyncio

from scripts import software_producer as sp
from tests.integration.m10.conftest import (
    context,
    documentation,
    implementation,
    section,
    target,
)
from tests.integration.software import CaseLoader, Template, copy_of


def test_t03_same_target_after_newer_ingestion(software_template: Template) -> None:
    """Uses its own copy: it ingests a newer snapshot record between the requests."""

    async def run() -> None:
        async with copy_of(software_template) as case:
            first = await context(case, "dave", documentation(target("a1", "b1"), ["retry"]))
            token = first["followup"]["token"]
            # A newer ledger snapshot appears between the two requests.
            newer = sp.entity(
                sp.ident("snapshot/a3", "entity"),
                "SourceSnapshot",
                "ledger a3",
                "sw-ledger",
                **{
                    sp.S + "repositoryRef": [sp.repository_id("ledger")],
                    sp.S + "commitId": [sp.lit("a" * 40)],
                },
            )
            await CaseLoader(case).apply_changeset(
                sp.operations([newer]),
                author="indexer",
                reviewer="reviewer",
                base=await case.knowledge.head(),
            )
            assert await case.knowledge.head() != first["revision"]
            second = await context(
                case, "dave", implementation(target("a1", "b1"), ["retry"], token)
            )
            assert second["revision"] == first["revision"]
            assert second["structured"]["target"] == first["structured"]["target"]
            assert section(second, "implementation") == []  # retry exists only in a2/b2

            # A token is bound to its principal and to the first request's target.
            await context(
                case, "alice", implementation(target("a1", "b1"), ["retry"], token), status=400
            )
            await context(
                case, "dave", implementation(target("a2", "b2"), ["retry"], token), status=400
            )

    asyncio.run(run())
