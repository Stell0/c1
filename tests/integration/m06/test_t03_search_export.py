"""M06-T03: search and export operate on readable document parts only."""

from __future__ import annotations

import asyncio
import json
import uuid
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m06.conftest import (
    ROOT,
    _apply_as_service,
    _service_token,
    install_scoped_document,
)

CORE = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def test_t03_search_and_export_are_authorized() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, scopes, _revision1, revision2 = await install_scoped_document(case)
            golden = json.loads(
                (ROOT / "fixtures/scoped-document/expected/search.json").read_text(encoding="utf-8")
            )
            document = quote(fixture["document_id"], safe="")
            notes = quote(fixture["notes_id"], safe="")
            for principal in ("alice", "bob", "carol"):
                result = await case.request(
                    "GET",
                    "/v1/documents",
                    actor=principal,
                    params={"text_contains": golden["query"]},
                )
                assert result.status_code == 200, result.text
                ids = [item["document"]["id"] for item in result.json()["items"]]
                assert ids == golden["matches"][principal]

            for principal in ("alice", "bob"):
                exported = await case.request(
                    "GET",
                    f"/v1/documents/{document}/export",
                    actor=principal,
                    params={"format": "jsonld", "revision": revision2},
                )
                assert exported.status_code == 200, exported.text
                body = exported.text
                hidden_ids = (
                    "document-part/00000073-0000-4000-8000-000000000000",
                    "document-part/00000074-0000-4000-8000-000000000000",
                    "document-part/00000075-0000-4000-8000-000000000000",
                    "document-part/00000076-0000-4000-8000-000000000000",
                )
                hidden_for_reader = hidden_ids if principal == "alice" else hidden_ids[2:]
                for hidden_id in hidden_for_reader:
                    assert hidden_id not in body
                assert "Legal review is required" not in body
                assert "NotImplementedError" not in body

                text_export = await case.request(
                    "GET",
                    f"/v1/documents/{document}/export",
                    actor=principal,
                    params={"format": "text", "revision": revision2},
                )
                assert text_export.status_code == 200, text_export.text
                assert "Legal review is required" not in text_export.text

            legal_search = await case.request(
                "GET",
                f"/v1/documents/{notes}/parts",
                actor="carol",
                params={"text_contains": "zebra-token"},
            )
            assert legal_search.status_code == 200, legal_search.text
            assert legal_search.json()["count"] == 1

            before_duplicate = await case.request(
                "GET",
                "/v1/documents",
                actor="alice",
                params={"text_contains": "troubleshooting"},
            )
            assert before_duplicate.status_code == 200, before_duplicate.text
            assert before_duplicate.json()["count"] == 1
            hidden_parts = []
            for order, text in (
                ("H", "private-handbook-only"),
                ("I", "Troubleshooting starts with the documented checks."),
            ):
                hidden_parts.append(
                    {
                        "kind": "create",
                        "scope_id": scopes["doc-legal"],
                        "record": {
                            "id": "urn:c1:instance:dev:document-part/" + str(uuid.uuid4()),
                            "types": [CORE + "DocumentPart"],
                            "properties": {
                                CORE + "partOfDocument": [fixture["document_id"]],
                                CORE + "orderKey": [{"lexical": order, "datatype": XSD + "string"}],
                                CORE + "text": [{"lexical": text, "datatype": XSD + "string"}],
                                CORE + "partKind": [
                                    {"lexical": "text", "datatype": XSD + "string"}
                                ],
                            },
                        },
                    }
                )
            await _apply_as_service(
                case,
                await _service_token(case),
                hidden_parts,
                "Add hidden-only and duplicate search terms",
            )
            after_duplicate = await case.request(
                "GET",
                "/v1/documents",
                actor="alice",
                params={"text_contains": "troubleshooting"},
            )
            assert after_duplicate.status_code == 200, after_duplicate.text

            def observation(body: dict[str, object]) -> dict[str, object]:
                return {key: value for key, value in body.items() if key != "revision"}

            assert observation(before_duplicate.json()) == observation(after_duplicate.json())
            hidden_term_results = {}
            for principal in ("alice", "bob"):
                result = await case.request(
                    "GET",
                    "/v1/documents",
                    actor=principal,
                    params={"text_contains": "private-handbook-only"},
                )
                hidden_term_results[principal] = result
            carol_hidden_term = await case.request(
                "GET",
                "/v1/documents",
                actor="carol",
                params={"text_contains": "private-handbook-only"},
            )
            for principal, result in hidden_term_results.items():
                assert result.status_code == 200, result.text
                assert result.json()["count"] == 0, principal
            assert carol_hidden_term.status_code == 200, carol_hidden_term.text
            assert [item["document"]["id"] for item in carol_hidden_term.json()["items"]] == [
                fixture["document_id"]
            ]

    asyncio.run(run())
