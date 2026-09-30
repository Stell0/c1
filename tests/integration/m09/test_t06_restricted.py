"""M09-T06: restricted or incomplete code never leaks through a package."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from scripts import software_producer as sp
from tests.integration.m09.conftest import package, shop_symbol, target, units, volatile
from tests.integration.software import Template, copy_of

HIDDEN_PATH = "shop/pricing_internal.py"


def test_t06_restricted_dependency_is_an_authorized_gap(
    software_template: Template, software_twin_template: Template
) -> None:
    """Uses fresh copies of the loaded repository and of its twin without the module."""

    async def run() -> None:
        async with copy_of(software_template) as case:
            dave = await package(case, "dave", shop_symbol(), target("a1", "b1"))
            carol = await package(case, "carol", shop_symbol(), target("a1", "b1"))

            # Dave sees the readable call site and a fixed gap, nothing about the module.
            submit = next(
                unit for unit in units(dave, "implementation") if unit["kind"] == "code-unit"
            )
            assert "pricing_internal.price(order)" in submit["text"]
            assert submit["code_completeness"] == "complete-unit"
            metadata = json.dumps(
                {
                    **dave["structured"],
                    "sections": {
                        name: [{k: v for k, v in unit.items() if k != "text"} for unit in items]
                        for name, items in dave["structured"]["sections"].items()
                    },
                }
            )
            assert HIDDEN_PATH not in metadata and "pricing_internal" not in metadata
            assert HIDDEN_PATH not in dave["markdown"]
            assert any(gap["kind"] == "dependencies" for gap in dave["structured"]["gaps"])

            # Carol's package includes the restricted dependency as its own unit.
            hidden = [
                unit for unit in units(carol, "implementation") if unit["path"] == HIDDEN_PATH
            ]
            assert len(hidden) == 1 and hidden[0]["kind"] == "dependency-unit"

            # Citation expansion of the hidden part is the uniform not-found answer.
            response = await case.request(
                "GET", "/v1/resources/" + quote(hidden[0]["part_id"], safe=""), actor="dave"
            )
            unknown = await case.request(
                "GET",
                "/v1/resources/" + quote(sp.ident("part/never-written", "part"), safe=""),
                actor="dave",
            )
            assert response.status_code == unknown.status_code == 404
            assert response.json() == unknown.json()

            # Code completeness is carried from the stored part kind, never guessed.
            for unit in units(carol):
                if "code_completeness" in unit:
                    expected = (
                        "complete-unit" if unit["part_kind"].startswith("code-unit") else "excerpt"
                    )
                    assert unit["code_completeness"] == expected, unit["id"]
                    label = "complete unit" if expected == "complete-unit" else "excerpt"
                    assert f"{unit['language']} {label}" in carol["markdown"]

            # Noninterference: byte-identical to a twin that never had the module.
            async with copy_of(software_twin_template) as twin:
                other = await package(twin, "dave", shop_symbol(), target("a1", "b1"))
                assert volatile(other["structured"], other["revision"]) == volatile(
                    dave["structured"], dave["revision"]
                )
                assert other["markdown"].replace(other["revision"], "<revision>") == dave[
                    "markdown"
                ].replace(dave["revision"], "<revision>")

    asyncio.run(run())
