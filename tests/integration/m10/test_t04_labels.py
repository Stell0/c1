"""M10-T04: evidence roles and warnings are labelled, never merged or hidden."""

from __future__ import annotations

from c1.context.support import PUBLICATION_STATEMENT
from tests.integration.m10.conftest import context, documentation, implementation, section, target
from tests.integration.software import Software


def test_t04_evidence_labels_and_warnings(software: Software) -> None:
    async def run() -> None:
        case = software.case
        docs = await context(case, "carol", documentation(target("a1", "b1"), ["configuration"]))
        assert {u["role"] for u in section(docs, "guidance")} == {"normative"}
        assert {u["label"] for u in section(docs, "guidance")} == {"official guidance"}
        discrepancies = [u for u in section(docs, "warnings") if u["kind"] == "discrepancy"]
        quotes = {c.get("quote") for u in discrepancies for c in u["citations"]}
        assert {"Zero amounts are rejected.", "return amount >= 0"} <= quotes
        assert docs["structured"]["publication"] == PUBLICATION_STATEMENT

        impl = await context(case, "carol", implementation(target("a2", "b2"), ["retry"]))
        assert {u["role"] for u in section(impl, "implementation")} == {"structural"}
        assert {u["label"] for u in section(impl, "implementation")} == {
            "implementation evidence, not a supported procedure"
        }
        claims = section(impl, "interpretations")
        assert claims and {u["role"] for u in claims} == {"interpretive"}
        assert {u["origin"] for u in claims} == {"derived"}
        assert {u["role"] for u in section(impl, "observed-tests")} <= {"observed"}
        assert impl["structured"]["publication"] == PUBLICATION_STATEMENT
        assert "official guidance" not in str(section(impl, "implementation"))

    software.run(run())
