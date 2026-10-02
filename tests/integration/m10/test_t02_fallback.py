"""M10-T02: a focused second request returns only aspect-relevant implementation."""

from __future__ import annotations

from scripts import software_producer as sp
from tests.integration.m10.conftest import (
    context,
    documentation,
    implementation,
    missing,
    section,
    target,
)
from tests.integration.software import Software


def test_t02_focused_fallback(software: Software) -> None:
    async def run() -> None:
        case = software.case
        first = await context(
            case, "dave", documentation(target("a2", "b2"), ["retry", "timeout", "configuration"])
        )
        assert sorted(missing(first)) == ["Retry", "Timeout"]
        assert any(
            sp.aspect_id("configuration") in u["aspects"] for u in section(first, "guidance")
        )
        token = first["followup"]["token"]
        assert first["followup"]["revision"] == first["revision"]

        second = await context(
            case, "dave", implementation(target("a2", "b2"), ["retry", "timeout"], token)
        )
        code = section(second, "implementation")
        definitions = {u["symbol"]["label"] for u in code if u["kind"] == "code-unit"}
        assert definitions == {"ledger.api.create_invoice", "shop.ledger_client.post_invoice"}
        assert all(
            u["commit"] in {software.fixture["snapshots"][k]["commit"] for k in ("a2", "b2")}
            for u in code
        )
        texts = "".join(u["text"] for u in code)
        assert "def get_invoice" not in texts and "def submit_order" not in texts
        assert missing(second) == ["Timeout"]
        assert all(u["label"] == "implementation evidence, not a supported procedure" for u in code)
        assert second["revision"] == first["revision"]

    software.run(run())
