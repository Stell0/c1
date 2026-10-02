"""M11-T05: C1 approval is not publication; only an imported receipt is."""

from __future__ import annotations

import asyncio
from typing import Any

from scripts import software_producer as sp
from tests.integration.m11.conftest import (
    accept,
    context,
    draft_operations,
    fixture_check,
    propose,
    target,
    units,
    update,
)
from tests.integration.software import CaseLoader, Template, copy_of


def _receipt(draft: str, publisher: str, scope: str, key: str) -> list[dict[str, Any]]:
    activity = sp.activity_record(
        f"m11-publication/{key}", publisher, "publication-report", [], scope
    )
    report = sp.ident(f"m11-publication/{key}/report", "document")
    report_part = sp.ident(f"m11-publication/{key}/report/0", "part")
    text = "published docs/invoicing.md (synthetic report)"
    return [
        activity,
        {
            "id": report,
            "types": [sp.C1 + "Document"],
            "scope": scope,
            "properties": {
                sp.DCT + "title": [sp.lit("publication report " + key)],
                sp.C1 + "sourceRevision": [sp.lit("report:" + key)],
                sp.C1 + "contentDigest": [sp.lit("sha256:" + sp.sha256(text.encode()))],
            },
        },
        {
            "id": report_part,
            "types": [sp.C1 + "DocumentPart"],
            "scope": scope,
            "properties": {
                sp.C1 + "partOfDocument": [report],
                sp.C1 + "orderKey": [sp.lit(sp.order_key(1))],
                sp.C1 + "text": [sp.lit(text)],
                sp.C1 + "partKind": [sp.lit("text")],
            },
        },
        {
            "id": sp.ident(f"m11-publication/{key}/receipt", "record"),
            "types": [sp.S + "ExternalPublication"],
            "scope": scope,
            "properties": {
                sp.S + "draftRef": [draft],
                sp.S + "locator": [sp.lit("https://git.example.invalid/ledger/docs/invoicing.md")],
                sp.S + "publishedAt": [sp.lit("2026-03-05T12:00:00Z", "dateTimeStamp")],
                sp.S + "publisherRef": [publisher],
                sp.S + "activityRef": [activity["id"]],
                sp.S + "reportRef": [report],
            },
        },
    ]


def test_t05_separate_publication(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            bob = (await case.principal("bob")).id
            check = fixture_check(software_template)
            operations, ids = draft_operations(software_template, bob, check=check)
            status, view = await propose(case, "bob", operations)
            assert status == 200, view
            await accept(case, view, "dave")
            approved, _ = draft_operations(software_template, bob, check=check, state="approved")
            record = next(op["record"] for op in approved if op["record"]["id"] == ids["draft"])
            status, view = await propose(
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
            assert status == 200 and view["state"] == "validated", view
            await accept(case, view, "dave")

            package = await context(case, "bob", update(target("a2", "b2")))
            [draft] = units(package, "drafts", "draft")
            assert (draft["draft_state"], draft["publication_state"]) == (
                "approved",
                "not-published",
            )

            # Bob cannot record a publication: never in his drafting scope, and he
            # holds no creation right in the receipt scope.
            in_drafts = sp.operations(_receipt(ids["draft"], bob, "drafts-bob", "bob-drafts"))
            status, view = await propose(case, "bob", in_drafts)
            assert status == 200 and "C1-CS-052" in view.get("codes", []), view
            in_receipts = sp.operations(_receipt(ids["draft"], bob, "sw-publications", "bob"))
            status, view = await propose(case, "bob", in_receipts)
            assert status != 200 or view.get("state") != "validated", view

            # The publisher's imported report is the only publication record.
            ci = software_template.loaded["principals"]["ci"]
            loader = CaseLoader(case)
            await loader.apply_changeset(
                sp.operations(_receipt(ids["draft"], ci, "sw-publications", "ci")),
                author="ci",
                reviewer="reviewer",
                base=(await loader.request("GET", "/v1/instance", actor="admin"))[
                    "knowledge_revision"
                ],
            )
            published = await context(case, "bob", update(target("a2", "b2")))
            [draft] = units(published, "drafts", "draft")
            assert draft["publication_state"] == "published"
            [receipt] = draft["publications"]
            assert receipt["locator"] == ["https://git.example.invalid/ledger/docs/invoicing.md"]
            assert receipt["publisher"] == ci
            # The locator is inert text in Markdown; nothing is fetched.
            assert "git.example.invalid" in published["markdown"]
            assert "](https://git.example.invalid" not in published["markdown"]

    asyncio.run(run())
