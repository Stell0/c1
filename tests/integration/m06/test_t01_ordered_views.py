"""M06-T01: revisions reconstruct the authorized parts in stable order."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m06.conftest import ROOT, install_scoped_document


def test_t01_ordered_views_match_golden_part_ids() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, _scopes, revision1, revision2 = await install_scoped_document(case)
            document_id = quote(fixture["document_id"], safe="")
            for principal in ("alice", "bob", "carol"):
                golden = json.loads(
                    (ROOT / f"fixtures/scoped-document/expected/{principal}.json").read_text(
                        encoding="utf-8"
                    )
                )
                for rev_name, revision in (("revision1", revision1), ("revision2", revision2)):
                    response = await case.request(
                        "GET",
                        f"/v1/documents/{document_id}",
                        actor=principal,
                        params={"revision": revision},
                    )
                    assert response.status_code == 200, response.text
                    payload = response.json()
                    by_id = await case.request(
                        "GET",
                        "/v1/documents/by-id",
                        actor=principal,
                        params={"document_id": fixture["document_id"], "revision": revision},
                    )
                    assert by_id.status_code == 200, by_id.text
                    assert by_id.json() == payload
                    assert isinstance(payload, dict)
                    actual = [item["part_id"] for item in payload["parts"]]
                    assert actual == golden[rev_name]
                    assert payload["revision"] == revision
                    if rev_name == "revision2":
                        text_by_id = {item["part_id"]: item["text"] for item in payload["parts"]}
                        assert (
                            text_by_id[
                                "urn:c1:instance:dev:document-part/00000072-0000-4000-8000-000000000000"
                            ]
                            == golden["text_revision2"][
                                "urn:c1:instance:dev:document-part/00000072-0000-4000-8000-000000000000"
                            ]
                        )
                        assert len({item["order_key"] for item in payload["parts"]}) == len(
                            payload["parts"]
                        )
                        for output_format, suffix in (("markdown", "md"), ("text", "txt")):
                            rendered = await case.request(
                                "GET",
                                f"/v1/documents/{document_id}/render",
                                actor=principal,
                                params={"revision": revision, "format": output_format},
                            )
                            assert rendered.status_code == 200, rendered.text
                            expected_text = (
                                ROOT / f"fixtures/scoped-document/expected/{principal}.{suffix}"
                            ).read_text(encoding="utf-8")
                            if suffix == "md":
                                # Markdown fixture files have the repository's
                                # required final newline; rendered strings do not.
                                expected_text = expected_text.rstrip("\n")
                            assert rendered.json()["content"] == expected_text

    asyncio.run(run())
