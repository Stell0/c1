"""M11-T01: both sides of the feature, the explicit contract, and unknown compatibility."""

from __future__ import annotations

import asyncio

from scripts import software_producer as sp
from tests.integration.m11.conftest import context, target, units, update
from tests.integration.software import Template, copy_of


def test_t01_both_sides_of_the_feature(software_template: Template) -> None:
    async def run() -> None:
        async with copy_of(software_template) as case:
            package = await context(case, "bob", update(target("a2", "b2")))
            assert package["structured"]["publication"].startswith("Prepared for the requesting")
            responsible = {
                unit["symbol"]["label"]: unit
                for unit in units(package, "responsibilities", "code-unit")
            }
            assert set(responsible) == {"ledger.api.create_invoice", "shop.client.submit_order"}
            assert (
                "implementsOperation" in responsible["ledger.api.create_invoice"]["responsibility"]
            )
            assert responsible["shop.client.submit_order"]["responsibility"] == [
                "declaredCall",
                "implementsCapability",
            ]
            assert {unit["repository"] for unit in responsible.values()} == {
                sp.repository_id("ledger"),
                sp.repository_id("shop"),
            }
            assert {unit["commit"] for unit in responsible.values()} == {
                software_template.loaded["planner"].commit("a2"),
                software_template.loaded["planner"].commit("b2"),
            }
            # The interface contract: the 1.1.0 contract part and both explicit links.
            contract = units(package, "interface-contract", "contract-part")
            assert [unit["document_id"] for unit in contract] == [sp.file_id("a2", "openapi.json")]
            assert '"version": "1.1.0"' in contract[0]["text"]
            create = [
                unit
                for unit in units(package, "interface-contract", "operation")
                if unit["operation"]["operation_id"] == "createInvoice"
            ]
            assert len(create) == 1
            predicates = {item["predicate"].rsplit("#", 1)[1] for item in create[0]["basis"]}
            assert predicates == {"implementsOperation", "declaredCall"}
            # No live run covers a2+b2: compatibility stays unknown.
            [pair] = units(package, "compatibility")
            assert pair["status"] == "unknown" and pair["runs"] == []
            # Matching names never link: each `validate` appears only as a direct
            # same-snapshot dependency of its own repository's responsibility.
            commits = {unit["symbol"]["label"]: unit["commit"] for unit in responsible.values()}
            dependencies = {
                unit["symbol"]["label"]: unit["commit"]
                for unit in units(package, "responsibilities", "dependency-unit")
            }
            assert dependencies["ledger.api.validate"] == commits["ledger.api.create_invoice"]
            assert dependencies["shop.client.validate"] == commits["shop.client.submit_order"]
            assert all(
                "validate" not in str(item.get("assertion_id"))
                and "validate" not in repr(item).lower()
                for unit in units(package, "interface-contract", "operation")
                for item in unit["basis"]
            )
            markdown = package["markdown"]
            assert "compatibility is unknown" in markdown

            # The a1+b1 target has a live run for exactly that pair.
            earlier = await context(case, "bob", update(target("a1", "b1", contract="a1")))
            [observed] = units(earlier, "compatibility")
            assert observed["status"] == "observed"
            assert [item["result"] for item in observed["runs"]] == ["pass"]

            # Closed grammar: one repository, aspects, or a goal are rejected.
            for body in (
                update(target("a2")),
                update(target("a2", "b2"), aspects=["retry"]),
                update(target("a2", "b2"), goal="conformance"),
            ):
                rejected = await context(case, "bob", body, status=400)
                assert rejected["code"] == "C1-CX-001"

    asyncio.run(run())
