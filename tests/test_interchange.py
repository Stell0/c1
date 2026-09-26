"""Local checks for the M01 interchange mapping; live persistence is M01-T07."""

from __future__ import annotations

import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast

import pytest
from rdflib import Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, XSD

from probes.interchange import from_document, load_jsonld, schema, to_document


def fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((Path(__file__).parents[1] / "probes/fixtures/assertion.jsonld").read_text()),
    )


def test_assertion_round_trip_preserves_identity_literals_and_provenance() -> None:
    original = load_jsonld(fixture())
    document = to_document(fixture())
    restored = load_jsonld(from_document(document))
    statement = URIRef("urn:c1:m01:statement-1")
    assert isomorphic(original, restored)
    assert (statement, RDF.subject, URIRef("urn:c1:m01:entity-tesla")) in restored
    assert (URIRef("urn:c1:m01:entity-tesla"), RDFS.label, Literal("Tesla", lang="en")) in restored
    assert (
        URIRef("urn:c1:m01:amount-1"),
        URIRef("urn:c1:m01:amount"),
        Literal("42.5000", datatype=XSD.decimal),
    ) in restored
    assert (
        statement,
        URIRef("http://www.w3.org/ns/prov#wasGeneratedBy"),
        URIRef("urn:c1:m01:import-1"),
    ) in restored
    assert document["triples"] and schema()[0]["@id"] == "ProbeGraph"


def test_rejects_remote_context_before_any_request() -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"@context": {}}')

        def log_message(self, _format: str, *args: object) -> None:
            pass

    try:
        server = HTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("local socket creation denied by execution sandbox")
    server.timeout = 0.2
    worker = Thread(target=server.handle_request)
    worker.start()
    try:
        value = fixture()
        value["@graph"][0]["@context"] = f"http://127.0.0.1:{server.server_port}/context"
        with pytest.raises(ValueError, match="not the bundled context"):
            to_document(value)
        worker.join(timeout=1)
        assert requests == []
    finally:
        server.server_close()
        worker.join(timeout=1)


@pytest.mark.parametrize(
    "injection",
    [{"@import": "https://example.test/context"}, {"@context": "https://example.test/context"}],
)
def test_rejects_nested_context_and_import(injection: dict[str, str]) -> None:
    value = fixture()
    value["@graph"][0]["metadata"] = {"nested": injection}
    with pytest.raises(ValueError, match="@import|not the bundled context"):
        load_jsonld(value)


def test_shacl_rejects_missing_provenance() -> None:
    value = deepcopy(fixture())
    del value["@graph"][0]["wasGeneratedBy"]
    with pytest.raises(ValueError, match="SHACL"):
        to_document(value)
