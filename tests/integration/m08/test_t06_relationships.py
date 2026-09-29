"""M08-T06: every relationship names its basis; nothing infers a runtime call."""

from __future__ import annotations

from scripts import software_producer as sp
from tests.integration.m08.conftest import Software, lookup_all, snapshot, symbol

S = "urn:c1:ns:software#"
SUBMIT = symbol("shop", "`shop.client`/submit_order().")
CREATE = symbol("ledger", "`ledger.api`/create_invoice().")
OPERATION = sp.operation_id("ledger", "createInvoice")


def test_t06_relationship_basis_and_mock_versus_observed(software: Software) -> None:
    case = software.case

    async def run() -> None:
        target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
        items = await lookup_all(
            case,
            "carol",
            {"target": target, "select": {"operation_id": OPERATION}},
        )
        relationships = [item for item in items if item["kind"] == "relationship"]
        found = {
            (item["predicate"], item["subject"], item["object"]): item for item in relationships
        }
        assert found[(S + "declaredCall", SUBMIT, OPERATION)]["basis"] == "declared"
        assert found[(S + "implementsOperation", CREATE, OPERATION)]["basis"] == "declared"
        assert found[(S + "interpretedCall", SUBMIT, CREATE)]["basis"] == "interpretive"
        live = sp.ident("test-run/live-a1b1", "test-run")
        assert found[(S + "exercised", live, OPERATION)]["basis"] == "observed"
        for item in relationships:
            if item["predicate"] == S + "staticCall":
                assert item["basis"] == "static-extraction"
        # A reference occurrence is structural only; no relationship claims a
        # runtime call from shop to ledger except the observed live run.
        occurrences = [item for item in items if item["kind"] == "occurrence"]
        assert occurrences and {item["basis"] for item in occurrences} == {"structural"}
        assert not [
            item
            for item in relationships
            if item["predicate"] == S + "staticCall"
            and item["object"] == CREATE
            and str(item["evidence"]["citation"]["path"]).startswith("shop/")
        ]

        # The mocked b2 run is labeled mocked and never exercised the ledger operation.
        b2 = await lookup_all(
            case,
            "carol",
            {"target": {"snapshots": [snapshot("b2")]}, "kinds": ["runs", "relationships"]},
        )
        runs = [item for item in b2 if item["kind"] == "run"]
        assert [(item["integration_mode"], item["mocked_products"]) for item in runs] == [
            ("mocked", [sp.product_id("ledger")])
        ]
        assert not [
            item
            for item in b2
            if item["kind"] == "relationship"
            and item["predicate"] == S + "exercised"
            and item["subject"] == runs[0]["id"]
        ]

    software.run(run())
