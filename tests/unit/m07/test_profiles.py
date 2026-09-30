from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import c1.context.profiles as context_profiles
from c1.changes.profiles import load_candidate
from c1.context.profiles import (
    ContextProfile,
    ContextProfileCatalog,
    load_context_profile,
    profile_digest,
)
from c1.interchange import validate_records
from c1.model.diagnostics import ProfileError
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, DCTERMS, SKOS
from c1.storage.schema import generated_classes, generated_core_schema

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "profiles" / "context" / "graph-context.json"


def data(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(PROFILE.read_text())
    value.update(changes)
    return value


def test_graph_context_contract_and_catalog() -> None:
    catalog = ContextProfileCatalog()
    profile = catalog.get("graph-context", "1")
    assert profile.anchor_types == [C1 + "Entity"]
    assert profile.target_types == ["urn:c1:ns:batteries#BatteryVersion"]
    assert profile.topic_expand == "off"
    assert profile.topic_predicate == DCTERMS + "subject"
    assert profile.fact_predicates == "declared"
    assert profile.conflict_basis == "declared"
    assert profile.measurement_predicate == "urn:c1:ns:batteries#measurementRef"
    assert profile.document_source_predicate == DCTERMS + "source"
    assert len(profile.paths[0].steps) == profile.paths[0].max_depth == 3
    assert [step.predicate.rsplit("#", 1)[-1] for step in profile.paths[0].steps] == [
        "hasProduct",
        "hasComponent",
        "hasVersion",
    ]
    assert catalog.digest("graph-context", "1") == profile_digest(profile)
    # M09 adds the software-task `test-development` profile to the same catalog.
    assert [item for item in catalog.catalog() if item["name"] == "graph-context"] == [
        {
            "name": "graph-context",
            "version": "1",
            "digest": profile_digest(profile),
            "anchor_types": [C1 + "Entity"],
            "fields": ["capacity", "cycle_life", "energy_density"],
        }
    ]
    schema = ContextProfile.model_json_schema()
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": "write a summary"},
        {"code": "print(1)"},
        {"expression": "x > 1"},
        {"version": 1},
        {"name": "../../untrusted"},
        {"anchor_types": []},
        {"target_types": ["relative"]},
        {"topic_expand": "automatic"},
        {"topic_predicate": "relative"},
        {"fact_predicates": "sparql"},
        {"fact_predicates": ["urn:test:a", "urn:test:a"]},
        {"fields": {"capacity": "capacity + 1"}},
        {"fields": {"bad field": "urn:test:p"}},
        {"sections": ["arbitrary prompt"]},
        {"sections": ["facts"]},
        {"order": "similarity"},
        {"group_by": "project"},
        {"conflict_basis": "different_targets"},
        {"measurement_predicate": "relative"},
        {"required_qualifiers": {"relative": ["urn:test:q"]}},
        {"required_qualifiers": {"urn:test:p": ["urn:test:undeclared"]}},
        {"required_qualifiers": {"urn:test:p": "urn:c1:ns:batteries#unit"}},
        {"role_types": {"bad role": ["urn:test:Product"]}},
        {"role_types": {"product": ["relative"]}},
        {"role_types": {"product": ["urn:test:Product", "urn:test:Product"]}},
        {
            "paths": [
                {
                    "steps": [{"predicate": "urn:test:p", "direction": "out", "code": "x"}],
                    "max_depth": 1,
                }
            ]
        },
        {"paths": [{"steps": [{"predicate": "urn:test:p", "direction": "both"}], "max_depth": 1}]},
        {"paths": [{"steps": [{"predicate": "urn:test:p", "direction": "out"}], "max_depth": 4}]},
        {
            "paths": [
                {"steps": [{"predicate": "urn:test:p", "direction": "out"}], "max_depth": True}
            ]
        },
    ],
)
def test_profile_rejects_executable_unknown_and_unbounded_data(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ContextProfile.model_validate(data(**changes))


def test_paths_and_expansion_are_explicit() -> None:
    profile = ContextProfile.model_validate(
        data(
            topic_expand="narrower",
            fields={
                "component": {
                    "steps": [{"predicate": "urn:test:p", "direction": "in"}],
                    "max_depth": 1,
                }
            },
        )
    )
    assert profile.topic_expand == "narrower"
    with pytest.raises(ValidationError):
        ContextProfile.model_validate(
            data(
                paths=[
                    {"steps": [{"predicate": "urn:test:p", "direction": "out"}] * 2, "max_depth": 1}
                ]
            )
        )


def test_digest_uses_canonical_profile_data(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data(), sort_keys=True, indent=4))
    assert profile_digest(load_context_profile(PROFILE)) == profile_digest(
        load_context_profile(path)
    )


@pytest.mark.parametrize(
    "name,version",
    [("../graph-context", "1"), ("graph-context", "2"), ("https://example.org/profile", "1")],
)
def test_catalog_selection_cannot_load_paths_or_versions(name: str, version: str) -> None:
    with pytest.raises(ProfileError, match="C1-CX-002"):
        ContextProfileCatalog().get(name, version)


def test_local_loader_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{invalid json")
    with pytest.raises(ProfileError, match="C1-CX-002"):
        load_context_profile(path)
    path.write_text(json.dumps(data(prompt="untrusted")))
    with pytest.raises(ProfileError, match="C1-CX-002"):
        load_context_profile(path)
    link = tmp_path / "symlink.json"
    link.symlink_to(PROFILE)
    with pytest.raises(ProfileError, match="C1-CX-002"):
        load_context_profile(link)


def test_catalog_validates_all_entries_eagerly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context_profiles, "_catalog_root", lambda: tmp_path)
    (tmp_path / "graph-context.json").write_text(json.dumps(data()))
    (tmp_path / "unknown.json").write_text(json.dumps(data(name="unknown", prompt="untrusted")))
    with pytest.raises(ProfileError, match="C1-CX-002"):
        ContextProfileCatalog()


def test_catalog_rejects_duplicate_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context_profiles, "_catalog_root", lambda: tmp_path)
    for name in ("first.json", "second.json"):
        (tmp_path / name).write_text(json.dumps(data()))
    with pytest.raises(ProfileError, match="Duplicate context profile"):
        ContextProfileCatalog()


def test_topic_extension_installs_without_changing_core() -> None:
    core = ProfileRegistry()
    registry, name = load_candidate("topics")
    assert name == "topics"
    assert registry.profiles["core"] == core.profiles["core"]
    assert generated_core_schema(registry) == generated_core_schema(core)
    assert set(registry.classes) - set(core.classes) == {SKOS + "Concept"}
    assert [item["@id"] for item in generated_classes(registry, "topics")] == ["Concept"]
    concept = NodeRecord(
        id="urn:test:concept/batteries",
        types=[SKOS + "Concept"],
        properties={
            SKOS + "prefLabel": [LiteralValue(lexical="Batteries", datatype=XSD_STRING)],
            SKOS + "altLabel": [LiteralValue(lexical="Storage", datatype=XSD_STRING)],
            SKOS + "inScheme": ["urn:test:scheme"],
            C1 + "lifecycle": [LiteralValue(lexical="active", datatype=XSD_STRING)],
        },
    )
    assert validate_records([concept], registry).records == [concept]
    assert SKOS + "broader" not in registry.classes[SKOS + "Concept"].properties
    assert registry.predicates[SKOS + "broader"].ranges == (SKOS + "Concept",)
    assert registry.predicates[DCTERMS + "subject"].ranges == (SKOS + "Concept",)
