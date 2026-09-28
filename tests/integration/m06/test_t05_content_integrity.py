"""M06-T05: text digests and code completeness labels reflect stored parts."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Any
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m06.conftest import (
    _apply_as_service,
    _reject_as_service,
    _service_token,
    install_scoped_document,
)

CORE = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def test_t05_part_text_digest_and_code_completeness_labels() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, _scopes, _revision1, revision2 = await install_scoped_document(case)
            document = quote(fixture["document_id"], safe="")
            response = await case.request(
                "GET", f"/v1/documents/{document}", actor="carol", params={"revision": revision2}
            )
            assert response.status_code == 200, response.text
            parts = response.json()["parts"]
            for part in parts:
                assert part["text_length"] == len(part["text"])
                assert (
                    part["text_digest"] == hashlib.sha256(part["text"].encode("utf-8")).hexdigest()
                )

            rendered = await case.request(
                "GET",
                f"/v1/documents/{document}/render",
                actor="carol",
                params={"revision": revision2, "format": "markdown"},
            )
            assert rendered.status_code == 200, rendered.text
            assert "excerpt" in rendered.text
            assert "complete unit" in rendered.text
            assert "document is complete" not in rendered.text.casefold()

            exact_prefix = "prefix\r\n\t  trailing  cafe\u0301 😀 ````\n"
            long_text = exact_prefix + "x" * (200 * 1024)
            long_part_id = "urn:c1:instance:dev:document-part/" + str(uuid.uuid4())
            operation: dict[str, Any] = {
                "kind": "create",
                "scope_id": _scopes["doc-public"],
                "record": {
                    "id": long_part_id,
                    "types": [CORE + "DocumentPart"],
                    "properties": {
                        CORE + "partOfDocument": [fixture["document_id"]],
                        CORE + "orderKey": [{"lexical": "H", "datatype": XSD + "string"}],
                        CORE + "text": [{"lexical": long_text, "datatype": XSD + "string"}],
                        CORE + "partKind": [{"lexical": "text", "datatype": XSD + "string"}],
                    },
                },
            }
            service = await _service_token(case)
            await _apply_as_service(
                case, service, [operation], "Round-trip a large exact text part"
            )
            large = await case.request("GET", f"/v1/documents/{document}", actor="alice")
            assert large.status_code == 200, large.text
            large_part = next(
                item for item in large.json()["parts"] if item["part_id"] == long_part_id
            )
            assert large_part["text"] == long_text
            assert large_part["text_length"] == len(long_text)
            assert (
                large_part["text_digest"] == hashlib.sha256(long_text.encode("utf-8")).hexdigest()
            )

            for invalid_text, expected_code in (
                ("bad\x00text", "C1-DC-003"),
                ("bad\u0085text", "C1-DC-003"),
                ("x" * (300 * 1024), "C1-DC-004"),
            ):
                invalid: dict[str, Any] = {
                    **operation,
                    "record": {
                        **operation["record"],
                        "id": "urn:c1:instance:dev:document-part/" + str(uuid.uuid4()),
                        "properties": {
                            **operation["record"]["properties"],
                            CORE + "orderKey": [{"lexical": "I", "datatype": XSD + "string"}],
                            CORE + "text": [{"lexical": invalid_text, "datatype": XSD + "string"}],
                        },
                    },
                }
                await _reject_as_service(case, service, [invalid], expected_code)

    asyncio.run(run())
