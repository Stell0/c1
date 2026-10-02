"""M11-T03: a rule result is a review candidate; only attributed review contradicts."""

from __future__ import annotations

import asyncio

from scripts import software_producer as sp
from tests.integration.m11.conftest import INVOICING, context, parts_of, target, units, update
from tests.integration.software import CaseLoader, Template, copy_of


def test_t03_review_candidate_not_proof(software_template: Template) -> None:
    planner: sp.Planner = software_template.loaded["planner"]
    sections = parts_of(planner, *INVOICING)
    body = [part for part, name in sections.items() if name == "Creating an invoice"][-1]
    a2 = sp.snapshot_id("a2")
    contracts = {sp.part_id("a1", "openapi.json", 0), sp.part_id("a2", "openapi.json", 0)}

    async def run() -> None:
        async with copy_of(software_template) as case:
            package = await context(case, "bob", update(target("a2", "b2")))
            candidates = units(package, "changes", "applicability-record")
            assert {unit["state"] for unit in candidates} == {"needs-review"}
            assert {unit["basis"] for unit in candidates} == {"rule"}
            for unit in candidates:
                assert unit["statement"] == "a review candidate, not proof that the text is wrong"
                cited = {citation["part_id"] for citation in unit["citations"]}
                assert contracts <= cited
                assert {item.split("=", 1)[0] for item in unit["evidence_digests"]} >= contracts

            # An attributed review with a quoted reason adds `contradicted`.
            analyzer = software_template.loaded["principals"]["analyzer"]
            activity = sp.activity_record("m11-review", analyzer, "review-notes", [], "sw-ledger")
            review = {
                "id": sp.ident("m11-review/contradicted", "record"),
                "types": [sp.S + "ApplicabilityRecord"],
                "scope": "sw-ledger",
                "properties": {
                    sp.S + "subjectRef": [body],
                    sp.S + "targetSnapshotRef": [a2],
                    sp.S + "applicabilityState": [sp.lit("contradicted")],
                    sp.S + "applicabilityBasis": [sp.lit("review")],
                    sp.S + "activityRef": [activity["id"]],
                    sp.S + "evidencePartRef": [sp.part_id("a2", "openapi.json", 0)],
                    sp.S + "recordNote": [
                        sp.lit('The a2 contract requires "customer_id", not "customer".')
                    ],
                    sp.S + "reviewStatus": [sp.lit("confirmed")],
                },
            }
            await CaseLoader(case).apply_changeset(
                sp.operations([activity, review]),
                author="analyzer",
                reviewer="reviewer",
                base=(await CaseLoader(case).request("GET", "/v1/instance", actor="admin"))[
                    "knowledge_revision"
                ],
            )
            after = await context(case, "bob", update(target("a2", "b2")))
            [part] = [
                unit
                for unit in units(after, "document-structure", "document-part")
                if unit["part_id"] == body
            ]
            value = part["applicability"][a2]
            assert value["state"] == "contradicted"
            assert sorted((item["state"], item["basis"]) for item in value["records"]) == [
                ("contradicted", "review"),
                ("needs-review", "rule"),
            ]
            assert {unit["state"] for unit in units(after, "changes", "applicability-record")} == {
                "needs-review",
                "contradicted",
            }

    asyncio.run(run())
