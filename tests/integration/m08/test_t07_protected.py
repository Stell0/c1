"""M08-T07: restricted source never shapes another reader's view, even historically."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m03.conftest import LiveCase
from tests.integration.m08.conftest import (
    CaseLoader,
    lookup,
    lookup_all,
    snapshot,
)
from tests.integration.software import Template, copy_of

S = "urn:c1:ns:software#"
C1 = "urn:c1:ns:core#"
SKOS = "http://www.w3.org/2004/02/skos/core#"


def _canonical(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, sort_keys=True)


def test_t07_restricted_source_has_no_influence_and_follows_current_bindings(
    software_template: Template, software_twin_template: Template
) -> None:
    """Uses its own fresh copies: it writes, and compares against the twin load."""

    async def run() -> None:
        async with copy_of(software_template) as case:
            await checks(case, software_template.loaded, software_twin_template)

    asyncio.run(run())


async def checks(case: LiveCase, loaded: dict[str, Any], twin_template: Template) -> None:
    target = {"snapshots": [snapshot("a1"), snapshot("b1")]}
    dave = await lookup_all(case, "dave", {"target": target})
    carol = await lookup_all(case, "carol", {"target": target})

    def metadata(item: dict[str, Any]) -> str:
        """Everything C1 asserts about an item, excluding readable source text."""
        value = dict(item)
        citation = dict(value.get("citation") or {})
        citation.pop("excerpt", None)
        value["citation"] = citation
        evidence = dict(value.get("evidence") or {})
        if evidence.get("citation"):
            evidence["citation"] = {
                key: item for key, item in evidence["citation"].items() if key != "excerpt"
            }
        value["evidence"] = evidence
        return json.dumps(value)

    # Readable shop code may call the restricted module by name; C1 must not add
    # any metadata about it (symbol, path, coverage, or relationships).
    text = "".join(metadata(item) for item in dave)
    assert "pricing_internal" not in text
    assert any("pricing_internal.py" in json.dumps(item) for item in carol)
    dave_coverage = [item for item in dave if item["kind"] == "coverage"]
    assert all("shop/pricing_internal.py" not in item["analyzed"] for item in dave_coverage)

    # Noninterference: the same readers see byte-identical results in a twin
    # repository where the restricted-scope records were never written.
    async with copy_of(twin_template) as twin:
        twin_items = await lookup_all(twin, "dave", {"target": target})
        assert _canonical(twin_items) == _canonical(dave)
        first_twin = await lookup(twin, "dave", {"target": target, "limit": 7})
        first_real = await lookup(case, "dave", {"target": target, "limit": 7})
        assert first_twin["count"] == first_real["count"]
        assert first_twin["items"] == first_real["items"]

    # A hidden snapshot, a wrong-class member, and a missing ID answer alike.
    loader = CaseLoader(case)
    hidden = sp.ident("snapshot/hidden-restricted", "entity")
    await loader.apply_changeset(
        sp.operations(
            [
                sp.entity(
                    hidden,
                    "SourceSnapshot",
                    "shop restricted",
                    "sw-restricted",
                    **{
                        S + "repositoryRef": [sp.repository_id("shop")],
                        S + "commitId": [
                            {
                                "lexical": "f" * 40,
                                "datatype": "http://www.w3.org/2001/XMLSchema#string",
                            }
                        ],
                    },
                )
            ]
        ),
        author="indexer",
        reviewer="reviewer",
        base=await case.knowledge.head(),
    )
    responses = []
    for member in (hidden, sp.capability_id("invoice-creation"), sp.ident("missing", "entity")):
        response = await case.request(
            "POST",
            "/v1/software/lookup",
            actor="dave",
            json={"target": {"snapshots": [member]}},
        )
        responses.append((response.status_code, response.json()))
    assert responses[0] == responses[1] == responses[2]
    assert responses[0][0] == 404

    # Current bindings govern historical content: move b1's client module to
    # the restricted scope; Dave's a1/b1 view loses it, including old citations.
    client_file = sp.file_id("b1", "shop/client.py")
    proposed = await case.request(
        "POST",
        "/v1/access-scopes/" + quote("sw-restricted", safe="") + "/bindings",
        actor="erin",
        json={"resource_id": client_file},
    )
    assert proposed.status_code == 200, proposed.text
    operation = proposed.json()["id"]
    await case.grant("sw-restricted", "frank", "access_admin")
    approved = await case.request(
        "POST", f"/v1/security-operations/{quote(operation, safe='')}/approve", actor="frank"
    )
    assert approved.status_code == 200, approved.text
    applied = await case.request(
        "POST", f"/v1/security-operations/{quote(operation, safe='')}/apply", actor="erin"
    )
    assert applied.status_code == 200, applied.text
    after = await lookup_all(case, "dave", {"target": target, "kinds": ["occurrences"]})
    assert "shop/client.py" not in {item["citation"]["path"] for item in after}
    historical = await lookup_all(
        case,
        "dave",
        {"target": target, "kinds": ["occurrences"], "revision": loaded["revision"]},
    )
    assert "shop/client.py" not in {item["citation"]["path"] for item in historical}
    carol_after = await lookup_all(case, "carol", {"target": target, "kinds": ["occurrences"]})
    assert "shop/client.py" in {item["citation"]["path"] for item in carol_after}
