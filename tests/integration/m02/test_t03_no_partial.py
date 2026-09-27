"""M02-T03: unsupported input cannot fetch contexts or partly write a batch."""

from __future__ import annotations

import asyncio
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from c1.interchange import ValidatedBatch, import_jsonld
from c1.model.diagnostics import ProfileError
from c1.model.profiles import ProfileRegistry
from tests.integration.m02.conftest import fixture_payload, live_knowledge


def test_t03_invalid_tenth_record_persists_nothing() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        source = fixture_payload()
        valid_payload = {"@context": source["@context"], "@graph": source["@graph"][:9]}
        valid = import_jsonld(valid_payload, registry)
        assert len(valid.records) == 9
        unsupported = copy.deepcopy(source["@graph"][8])
        unsupported["@id"] = "urn:c1:instance:dev:source/00000003-0000-4000-8000-000000000000"
        unsupported["http://purl.org/dc/terms/title"] = {
            "@value": "invalid last item",
            "@type": "http://www.w3.org/2001/XMLSchema#duration",
        }
        bad_payload = {
            "@context": source["@context"],
            "@graph": source["@graph"][:9] + [unsupported],
        }

        async with live_knowledge(registry) as db:
            before_head = await db.head()
            before_log = await db.log()
            before_docs = await db.documents()
            with pytest.raises(ProfileError) as caught:
                import_jsonld(bad_payload, registry)
            assert caught.value.diagnostics[0].code == "C1-IX-020"
            assert await db.head() == before_head
            assert await db.log() == before_log
            assert await db.documents() == before_docs

            # The product storage client revalidates even a forged batch object.
            forged = valid.records[-1].model_copy(
                update={
                    "properties": {
                        **valid.records[-1].properties,
                        "urn:c1:ns:core#undeclared": [],
                    }
                }
            )
            mutated = ValidatedBatch(records=[*valid.records[:-1], forged])
            with pytest.raises(ProfileError) as guarded:
                await db.write_records(mutated, registry, expected_head=before_head)
            assert guarded.value.diagnostics[0].code == "C1-IX-011"
            assert await db.head() == before_head
            assert await db.log() == before_log
            assert await db.documents() == before_docs

    asyncio.run(run())


def test_t03_remote_context_causes_zero_http_requests() -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"@context": {}}')

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = fixture_payload()
        source["@context"] = f"http://127.0.0.1:{server.server_port}/context"

        async def run() -> None:
            registry = ProfileRegistry()
            async with live_knowledge(registry) as db:
                before_head = await db.head()
                before_log = await db.log()
                with pytest.raises(ProfileError) as caught:
                    import_jsonld(source, registry)
                assert caught.value.diagnostics[0].code == "C1-IX-001"
                assert await db.head() == before_head
                assert await db.log() == before_log

        asyncio.run(run())
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
