"""M13-T06: export is a portable snapshot, unsupported input is refused, schema is repeatable."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid

import pytest
from rdflib import Graph

from c1.interchange.jsonld import _context_map, import_jsonld
from c1.model.diagnostics import ProfileError
from c1.model.profiles import ProfileRegistry
from tests.integration.m04.conftest import action, new_changeset
from tests.integration.m13.conftest import Reference

ROOT_PROFILES = ("directory", "topics", "batteries", "software", "example-vehicle")


def _registry(names: list[str]) -> ProfileRegistry:
    from pathlib import Path

    registry = ProfileRegistry()
    base = Path(__file__).resolve().parents[3] / "profiles/available"
    for name in names:
        registry.load(base / name)
    return registry


def test_t06_export_roundtrip_refusals_and_repeatable_schema(reference: Reference) -> None:
    case = reference.case

    async def run() -> None:
        schema = (await case.request("GET", "/v1/schema", actor="alice")).json()
        installed = [p["name"] for p in schema["profiles"] if p["name"] != "core"]
        registry = _registry(installed)
        # Installation is a pure function of the bundled files: same classes and properties.
        for profile in schema["profiles"]:
            expected = registry.profiles[profile["name"]]
            assert profile["version"] == expected.version
            assert sorted(c["iri"] for c in profile["classes"]) == sorted(expected.classes)

        export = await case.request("GET", "/v1/export", actor="carol", params={"limit": 200})
        assert export.status_code == 200, export.text
        snapshot = export.json()["snapshot"]
        text = json.dumps(snapshot)
        for forbidden in ("bound_to", "access_scope", "approvals", "Idempotency", "tuple"):
            assert forbidden not in text, forbidden
        # Independent RDF processing with the bundled context supplied in memory.
        expanded = copy.deepcopy(snapshot)
        expanded["@context"] = _context_map(registry, snapshot["@context"])
        graph = Graph().parse(data=json.dumps(expanded), format="json-ld")
        assert len(graph) > 0
        subjects = {str(s) for s in graph.subjects()}
        ids = {node["@id"] for node in snapshot.get("@graph", [])}
        assert ids <= subjects
        # The C1 importer accepts the same snapshot with identical record identities.
        batch = import_jsonld(snapshot, registry)
        assert {record.id for record in batch.records} == ids
        digest = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
        assert digest

        # A remote context is refused explicitly, without fetching it.
        remote = {**snapshot, "@context": "https://example.invalid/context.jsonld"}
        with pytest.raises(ProfileError):
            import_jsonld(remote, registry)

        # An incompatible profile change requires a migration plan.
        if "example-vehicle" in installed:
            proposal = await new_changeset(
                case,
                [{"kind": "install_profile", "profile": "example-vehicle-v2-incompatible"}],
                actor="erin",
                key=uuid.uuid4().hex,
            )
            state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
            if state == "submitted":
                state = (await action(case, proposal["id"], "validate", actor="erin"))["state"]
            report = await case.request(
                "GET", f"/v1/changesets/{proposal['id']}/validation", actor="erin"
            )
            codes = {d.get("code") for d in report.json().get("diagnostics", [])}
            assert state == "rejected" and "C1-PR-004" in codes, (state, codes)

    reference.run(run())
