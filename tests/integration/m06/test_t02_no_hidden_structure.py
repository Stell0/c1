"""M06-T02: inaccessible part structure never reaches document responses."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

from tests.integration.m03.conftest import live_case
from tests.integration.m06.conftest import ROOT, install_scoped_document

HIDDEN = (
    "urn:c1:instance:dev:document-part/00000073-0000-4000-8000-000000000000",
    "urn:c1:instance:dev:document-part/00000074-0000-4000-8000-000000000000",
    "urn:c1:instance:dev:document-part/00000075-0000-4000-8000-000000000000",
    "urn:c1:instance:dev:document-part/00000076-0000-4000-8000-000000000000",
)


def _canonical(value: object) -> object:
    """Ignore generated revision, timestamp, and per-run ChangeSet fields."""
    if isinstance(value, dict):
        volatile = {"revision", "instance", "recorded_at", "changeset_id"}
        return {key: _canonical(item) for key, item in value.items() if key not in volatile}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def test_t02_no_hidden_structure_in_any_handbook_view() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, _scopes, _revision1, revision2 = await install_scoped_document(case)
            path = "/v1/documents/" + quote(fixture["document_id"], safe="")
            requests: tuple[tuple[str, str, str, dict[str, str]], ...] = (
                ("detail", "GET", path, {"revision": revision2}),
                (
                    "detail-by-id",
                    "GET",
                    "/v1/documents/by-id",
                    {"document_id": fixture["document_id"], "revision": revision2},
                ),
                ("parts", "GET", path + "/parts", {"revision": revision2}),
                (
                    "render-markdown",
                    "GET",
                    path + "/render",
                    {"revision": revision2, "format": "markdown"},
                ),
                (
                    "export-jsonld",
                    "GET",
                    path + "/export",
                    {"revision": revision2, "format": "jsonld"},
                ),
                (
                    "export-text",
                    "GET",
                    path + "/export",
                    {"revision": revision2, "format": "text"},
                ),
                ("history", "GET", path + "/history", {"limit": "100"}),
                (
                    "list",
                    "GET",
                    "/v1/documents",
                    {"title": "Handbook", "revision": revision2},
                ),
            )
            observations: dict[str, dict[str, Any]] = {}
            for name, method, endpoint, params in requests:
                response = await case.request(method, endpoint, actor="alice", params=params)
                assert response.status_code == 200, response.text
                body = response.content.decode("utf-8")
                for hidden_id in HIDDEN:
                    assert hidden_id not in body
                for marker in ("omitted", "redacted", "hidden"):
                    assert marker not in body.casefold()
                observations[name] = response.json()

            whole = observations["detail"]
            parts = observations["parts"]
            assert whole["parts"] == parts["items"]
            assert parts["count"] == 3
            history_golden = json.loads(
                (ROOT / "fixtures/scoped-document/expected/history.json").read_text(
                    encoding="utf-8"
                )
            )
            assert history_golden["document_id"] == fixture["document_id"]
            assert len(observations["history"]["items"]) == history_golden["revision_count"]

        # A second isolated database omits the hidden parts at creation. Every
        # public route must return the same authorized body and metadata.
        async with live_case() as isolated:
            (
                fixture_without_hidden,
                _scopes,
                _r1,
                revision_without_hidden,
            ) = await install_scoped_document(isolated, omit_hidden_parts=True)
            assert fixture_without_hidden["document_id"] == fixture["document_id"]
            isolated_path = "/v1/documents/" + quote(fixture["document_id"], safe="")
            for name, method, endpoint, params in requests:
                updated_params = dict(params)
                if "revision" in updated_params:
                    updated_params["revision"] = revision_without_hidden
                isolated_endpoint = endpoint.replace(path, isolated_path)
                response = await isolated.request(
                    method, isolated_endpoint, actor="alice", params=updated_params
                )
                assert response.status_code == 200, response.text
                assert _canonical(observations[name]) == _canonical(response.json())

    asyncio.run(run())
