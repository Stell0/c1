"""M09-T01: a target-specific package carries the required, usable context."""

from __future__ import annotations

import json
from urllib.parse import quote

from tests.integration.m09.conftest import (
    ledger_symbol,
    package,
    target,
    unit_for,
    units,
)
from tests.integration.software import Software, commit

RULE = "The amount must be greater than zero; zero is rejected with 422."


def test_t01_required_context_for_create_invoice(software: Software) -> None:
    async def run() -> None:
        case = software.case
        value = await package(case, "carol", ledger_symbol(), target("a1", "b1"))
        structured = value["structured"]
        markdown = value["markdown"]
        a1, b1 = commit(software, "a1"), commit(software, "b1")
        assert structured["interpretation"]["goal"] == "conformance"
        assert [item["id"] for item in structured["interpretation"]["target_symbols"]] == [
            ledger_symbol()
        ]

        # Normative: the documented rule and the pinned 1.0.0 contract, with text.
        documentation = [
            unit for unit in units(value, "normative") if unit["path"] == "docs/invoicing.md"
        ]
        assert any(RULE in unit["text"] for unit in documentation)
        assert all(unit["commit"] == a1 and unit["role"] == "normative" for unit in documentation)
        contract = unit_for(value, "normative", path="openapi.json")
        assert contract["commit"] == a1 and contract["kind"] == "contract-part"
        assert '"operationId": "createInvoice"' in contract["text"]
        assert '"version": "1.0.0"' in contract["text"]

        # Implementation: the complete a1 unit and its direct readable dependencies.
        definition = unit_for(value, "implementation", kind="code-unit")
        assert definition["path"] == "ledger/api.py" and definition["commit"] == a1
        assert definition["code_completeness"] == "complete-unit"
        assert definition["text"].startswith("def create_invoice(customer: str, amount: int)")
        dependencies = {
            unit["symbol"]["label"]: unit
            for unit in units(value, "implementation")
            if unit["kind"] == "dependency-unit"
        }
        invoice = next(unit for label, unit in dependencies.items() if label.endswith("Invoice"))
        assert invoice["path"] == "ledger/models.py" and "class Invoice:" in invoice["text"]
        assert any(unit["text"].startswith("def validate(") for unit in dependencies.values())

        # Interfaces, tests, fixtures, and execution instructions.
        operation = unit_for(value, "interfaces", kind="operation")
        assert operation["operation"]["operation_id"] == "createInvoice"
        assert {item["predicate"].rsplit("#")[-1] for item in operation["basis"]} == {
            "implementsOperation"
        }
        test = unit_for(value, "tests", path="tests/test_api.py")
        assert "def test_create_invoice_stores_invoice" in test["text"]
        assert test["status"] == "definition-only"
        fixture = unit_for(value, "fixtures", path="tests/conftest.py")
        assert "def sample_invoice" in fixture["text"]
        instruction = unit_for(value, "instructions", path="CONTRIBUTING.md")
        assert "python -m pytest tests" in instruction["text"]
        assert instruction["untrusted"] is True and instruction["role"] == "instruction"
        assert "Untrusted instruction text" in markdown

        # No item from another snapshot; every item carries text, not only IDs.
        pinned = {a1, b1}
        for unit in units(value):
            if "commit" in unit:
                assert unit["commit"] in pinned, unit
                assert unit["text"], unit
            assert unit["id"] in markdown
        # Only runs labelled other-target may name another snapshot, as their own target.
        a2, b2 = commit(software, "a2"), commit(software, "b2")
        for unit in units(value):
            if unit["kind"] == "test-run" and unit["match"] == "other-target":
                continue
            assert a2 not in json.dumps(unit) and b2 not in json.dumps(unit), unit["id"]

        # Every cited part and document resolves through generic authorized reads.
        for citation in structured["sources"]:
            for key in ("part_id", "document_id"):
                response = await case.request(
                    "GET", "/v1/resources/" + quote(citation[key], safe=""), actor="carol"
                )
                assert response.status_code == 200, (citation, response.text)
        part = await case.request(
            "GET", "/v1/resources/" + quote(definition["part_id"], safe=""), actor="carol"
        )
        assert part.json()["properties"]["urn:c1:ns:core#text"][0]["lexical"] == definition["text"]

    software.run(run())
