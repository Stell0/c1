"""M01-T07: real TerminusDB interchange and remote-context rejection."""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast

import pytest
from rdflib import Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, XSD

from probes.interchange import from_document, load_jsonld, schema, to_document
from probes.session import session

FIXTURE = Path(__file__).parents[3] / "probes/fixtures/assertion.jsonld"
STATEMENT = URIRef("urn:c1:m01:statement-1")
PROV = "http://www.w3.org/ns/prov#"


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_t07_interchange_round_trip() -> None:
    async def run() -> None:
        value = _fixture()
        original = load_jsonld(value)
        document = to_document(value)
        async with session(schema()) as live:
            await live.knowledge.insert([document], "M01-T07 interchange")
            stored = await live.knowledge.get(document["@id"])
            assert stored is not None
            restored = load_jsonld(from_document(stored))
            assert isomorphic(original, restored)
            assert (STATEMENT, RDF.subject, URIRef("urn:c1:m01:entity-tesla")) in restored
            assert (STATEMENT, RDF.predicate, URIRef("urn:c1:m01:hasAmount")) in restored
            assert (STATEMENT, RDF.object, URIRef("urn:c1:m01:amount-1")) in restored
            assert (
                URIRef("urn:c1:m01:entity-tesla"),
                RDFS.label,
                Literal("Tesla", lang="en"),
            ) in restored
            assert (
                URIRef("urn:c1:m01:amount-1"),
                URIRef("urn:c1:m01:amount"),
                Literal("42.5000", datatype=XSD.decimal),
            ) in restored
            assert (
                STATEMENT,
                URIRef(PROV + "wasGeneratedBy"),
                URIRef("urn:c1:m01:import-1"),
            ) in restored
            assert (
                STATEMENT,
                URIRef(PROV + "wasAttributedTo"),
                URIRef("urn:c1:m01:agent-1"),
            ) in restored

    asyncio.run(run())


def test_t07_remote_context_rejected_without_fetch_or_write() -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"@context": {}}')

        def log_message(self, _format: str, *args: object) -> None:
            pass

    # A bind failure is a failed live infrastructure check, never a skipped gate.
    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        value = _fixture()
        value["@graph"][0]["@context"] = f"http://127.0.0.1:{server.server_port}/context"

        async def run() -> None:
            async with session(schema()) as live:
                initial_head = await live.knowledge.head()
                with pytest.raises(ValueError, match="not the bundled context"):
                    document = to_document(value)
                    await live.knowledge.insert([document], "M01-T07 rejected context")
                assert await live.knowledge.head() == initial_head
                assert await live.knowledge.documents() == []

        asyncio.run(run())
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
