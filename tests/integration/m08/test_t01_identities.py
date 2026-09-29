"""M08-T01: unqualified names stay distinct; one capability links both products."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m08.conftest import (
    CaseLoader,
    Software,
    lookup_all,
    snapshot,
    symbol,
)

S = "urn:c1:ns:software#"
C1 = "urn:c1:ns:core#"
LEDGER_VALIDATE = "`ledger.api`/validate()."
SHOP_VALIDATE = "`shop.client`/validate()."


def test_t01_independent_identities_and_shared_capability(software: Software) -> None:
    case = software.case

    async def run() -> None:
        target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
        occurrences = await lookup_all(case, "carol", {"target": target, "kinds": ["occurrences"]})
        definitions = {
            (item["symbol"]["id"], item["target_member"])
            for item in occurrences
            if "definition" in item["roles"]
            and item["symbol"]["descriptors"] in {LEDGER_VALIDATE, SHOP_VALIDATE}
        }
        assert definitions == {
            (symbol("ledger", LEDGER_VALIDATE), snapshot("a1")),
            (symbol("shop", SHOP_VALIDATE), snapshot("b1")),
        }
        for repository, descriptors in (("ledger", LEDGER_VALIDATE), ("shop", SHOP_VALIDATE)):
            response = await case.request(
                "GET",
                "/v1/resources/" + quote(symbol(repository, descriptors), safe=""),
                actor="carol",
            )
            assert response.status_code == 200, response.text
            assert response.json()["properties"][S + "repositoryRef"] == [
                sp.repository_id(repository)
            ]

        capability = sp.capability_id("invoice-creation")
        relationships = await lookup_all(
            case,
            "carol",
            {"target": target, "select": {"capability_id": capability}, "kinds": ["relationships"]},
        )
        implementers = {
            item["subject"]
            for item in relationships
            if item["predicate"] == S + "implementsCapability" and item["object"] == capability
        }
        assert implementers == {
            symbol("ledger", "`ledger.api`/create_invoice()."),
            symbol("shop", "`shop.client`/submit_order()."),
        }
        assert {
            item["basis"]
            for item in relationships
            if item["predicate"] == S + "implementsCapability"
        } == {"interpretive"}

        async def counts() -> dict[str, Any]:
            values: dict[str, Any] = {}
            for cls in ("CodeRepository", "CodeSymbol", "SourceSnapshot"):
                found = await case.request(
                    "GET",
                    "/v1/entities?types=" + quote(S + cls, safe="") + "&limit=200",
                    actor="carol",
                )
                assert found.status_code == 200, found.text
                values[cls] = sorted(item["id"] for item in found.json()["items"])
            databases = await case.knowledge._request("GET", "/api/db/admin")
            values["databases"] = len(databases.json())
            return values

        before = await counts()
        # A project view is only a narrowing reference on existing identities.
        loader = CaseLoader(case)
        operations = []
        for key in ("ledger", "shop"):
            current = await case.request(
                "GET", "/v1/resources/" + quote(sp.product_id(key), safe=""), actor="carol"
            )
            record = current.json()
            properties = dict(record["properties"])
            properties[C1 + "projectReference"] = ["urn:c1:instance:dev:project/invoicing-view"]
            operations.append(
                {
                    "kind": "replace",
                    "resource_id": record["id"],
                    "record": {
                        "id": record["id"],
                        "types": record["types"],
                        "properties": properties,
                    },
                    "reason": "Add a project view",
                }
            )
        await loader.apply_changeset(
            operations,
            author="indexer",
            reviewer="reviewer",
            base=await case.knowledge.head(),
        )
        assert await counts() == before

    software.run(run())
