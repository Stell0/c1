"""M02-T03: unsupported JSON-LD is rejected before any remote resolution."""

from __future__ import annotations

from typing import Any

import pytest

from c1.interchange import import_jsonld
from c1.model.diagnostics import ProfileError

CONTEXT = "urn:c1:ns:core:context:1"
ENTITY = {
    "@id": "urn:c1:instance:dev:entity/00000000-0000-4000-8000-000000000001",
    "@type": "Entity",
    "label": "Ada",
    "lifecycle": "active",
}


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"@context": "http://127.0.0.1:65535/context"}, "C1-IX-001"),
        ({"@context": {"fake": "urn:x#"}}, "C1-IX-001"),
        ({"@import": "https://example.invalid/context"}, "C1-IX-002"),
        ({"@list": []}, "C1-IX-002"),
        ({"@id": "_:blank"}, "C1-IX-010"),
        ({"urn:unknown:predicate": "a"}, "C1-IX-011"),
        ({"label": {"@value": "Ada", "@type": "xsd:duration"}}, "C1-IX-020"),
    ],
)
def test_specific_unsupported_diagnostics(mutation: dict[str, Any], expected: str) -> None:
    payload: dict[str, Any] = {"@context": CONTEXT, "@graph": [{**ENTITY, **mutation}]}
    with pytest.raises(ProfileError) as caught:
        import_jsonld(payload)
    assert caught.value.diagnostics[0].code == expected


def test_no_remote_fetch_for_nonbundled_context() -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {
            "@context": f"http://127.0.0.1:{server.server_port}/context",
            "@graph": [ENTITY],
        }
        with pytest.raises(ProfileError) as caught:
            import_jsonld(payload)
        assert caught.value.diagnostics[0].code == "C1-IX-001"
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
