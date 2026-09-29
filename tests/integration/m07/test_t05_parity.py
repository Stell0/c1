"""M07-T05: facts carry resolvable citations and both renderings agree."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

from c1.changes.digest import canonical_json
from c1.context.structured import parity_identifiers, unit_citations
from c1.documents.render import escape_markdown_text
from tests.integration.m07.conftest import Batteries, package


def test_t05_usable_payload_and_format_parity(batteries: Batteries) -> None:
    async def run() -> None:
        result = await package(batteries.case, batteries.loaded)
        structured, markdown = result["structured"], result["markdown"]
        for unit in structured["facts"]:
            for claim in unit["claims"]:
                assert claim["value"] and claim["citations"]
                for citation in claim["citations"]:
                    for key in ("evidence_id", "source_id", "part_id", "document_id"):
                        if key in citation:
                            response = await batteries.case.request(
                                "GET",
                                "/v1/resources/" + quote(citation[key], safe=""),
                                actor="dave",
                            )
                            assert response.status_code == 200, (key, response.text)
                    if "selector" in citation:
                        response = await batteries.case.request(
                            "GET",
                            "/v1/resources/" + quote(citation["selector"]["id"], safe=""),
                            actor="dave",
                        )
                        assert response.status_code == 200, response.text
        text_section = markdown.split("## Text\n", 1)[1].split("## Disagreements", 1)[0]
        for citation in structured["text"]:
            assert escape_markdown_text(citation["excerpt"]) in text_section
        assert len(re.findall(r"\[\^\d+\]", text_section)) == len(structured["text"])
        facts_section = markdown.split("## Facts\n", 1)[1].split("## Text", 1)[0]
        for position, unit in enumerate(structured["facts"]):
            marker = "Unit: " + escape_markdown_text(unit["id"])
            assert marker in facts_section
            fragment = facts_section.split(marker, 1)[1]
            if position + 1 < len(structured["facts"]):
                following = structured["facts"][position + 1]
                fragment = fragment.split("Unit: " + escape_markdown_text(following["id"]), 1)[0]
            assert {int(n) for n in re.findall(r"\[\^(\d+)\]", fragment)} == {
                citation["n"] for citation in unit_citations(unit)
            }
        numbers = {citation["n"] for citation in structured["sources"]}
        assert {int(n) for n in re.findall(r"\[\^(\d+)\]:", markdown)} == numbers
        digest = hashlib.sha256(
            canonical_json(parity_identifiers(structured["facts"])).encode()
        ).hexdigest()
        assert structured["format_parity_digest"] == digest
        assert digest in markdown

    batteries.runner.run(run())
