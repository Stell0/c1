"""Fixture orchestration cannot silently combine independent schema installs."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest

from c1.model.ids import KINDS
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import document_to_record, record_to_document, records_to_documents
from probes.config import ROOT
from scripts.load_fixture import Loader


class RecordingLoader(Loader):
    """Record orchestration only; these tests do not prove backend integration."""

    def __init__(self, client: httpx.AsyncClient, *, resume: bool = False) -> None:
        super().__init__(client, {})
        self.head = "revision0"
        self.applied: list[tuple[list[dict[str, Any]], str]] = []
        self.created_scopes: list[str] = []
        self.resume = resume
        self.fixture = json.loads(
            (ROOT / "fixtures/cross-project-batteries/fixture.json").read_text()
        )

    async def whoami(self, actor: str) -> str:
        return "user:c1-dev." + actor

    async def grant_instance(self, member: str, role: str) -> None:
        pass

    async def _membership(self, scope_id: str, member: str, role: str) -> None:
        pass

    async def request(
        self,
        method: str,
        path: str,
        *,
        actor: str,
        json_body: object | None = None,
        expected: tuple[int, ...] = (200,),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if path == "/v1/instance":
            return {"knowledge_revision": self.head}
        if path == "/v1/catalog":
            return {"profile_versions": {"topics": "1.0.0"}}
        if method == "GET" and path == "/v1/access-scopes":
            return {
                "access_scopes": [
                    {"id": key, "label": label, "state": "active"}
                    for key, label in self.fixture["scopes"].items()
                ]
            }
        if method == "POST" and path == "/v1/access-scopes":
            assert isinstance(json_body, dict)
            self.created_scopes.append(json_body["id"])
            return {}
        if path.startswith("/v1/entities?ids="):
            return {"items": []}
        if path == "/v1/entities?label=Tesla&label_mode=exact":
            return {"items": [{"id": self.fixture["ids"]["tesla"]}]}
        raise AssertionError((method, path, actor))

    async def apply_changeset(
        self, operations: list[dict[str, Any]], *, author: str, reviewer: str, base: str
    ) -> dict[str, Any]:
        assert base == self.head
        self.applied.append((operations, base))
        self.head = "revision" + str(len(self.applied))
        return {"state": "applied"}


@pytest.mark.parametrize("resume", [False, True])
def test_batteries_profiles_install_individually_at_each_new_head(resume: bool) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            loader = RecordingLoader(client, resume=resume)
            result = await loader.load_batteries(resume_setup=resume)
            schema = [
                operations
                for operations, _ in loader.applied
                if operations[0]["kind"] == "install_profile"
            ]
            expected = ["batteries"] if resume else ["topics", "batteries"]
            assert schema == [[{"kind": "install_profile", "profile": name}] for name in expected]
            assert [base for _, base in loader.applied] == [
                "revision" + str(index) for index in range(len(loader.applied))
            ]
            assert len(loader.created_scopes) == (0 if resume else 4)
            assert result["state"] == "applied"

    asyncio.run(run())


def test_all_batteries_fixture_records_roundtrip_the_storage_mapping() -> None:
    def encode(value: str | LiteralValue) -> str:
        return json.dumps(
            value if isinstance(value, str) else value.model_dump(mode="json"), sort_keys=True
        )

    fixture = json.loads((ROOT / "fixtures/cross-project-batteries/fixture.json").read_text())
    registry = ProfileRegistry()
    for name in ("topics", "batteries"):
        registry.load(ROOT / "profiles/available" / name)
    specifications = [item for records in fixture["producers"].values() for item in records]
    specifications.extend([fixture["hidden_topic"], *fixture["ambiguity"]])
    records = [
        NodeRecord.model_validate({key: item[key] for key in ("id", "types", "properties")})
        for item in specifications
    ]
    documents = records_to_documents(records, registry, "urn:c1:instance:dev:")
    assert len(documents) == len(records)
    for original, document in zip(records, documents, strict=True):
        kind, _, suffix = original.id.removeprefix("urn:c1:instance:dev:").partition("/")
        if kind in KINDS:
            assert uuid.UUID(suffix).version == 4
        recovered = document_to_record(document, registry)
        assert recovered.id == original.id and recovered.types == original.types
        # RDF property values are sets; the storage mapper canonically orders them.
        assert record_to_document(recovered, registry, "urn:c1:instance:dev:") == document
        assert recovered.properties.keys() == original.properties.keys()
        for predicate, values in original.properties.items():
            assert {encode(value) for value in recovered.properties[predicate]} == {
                encode(value) for value in values
            }
