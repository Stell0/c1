"""M02-T07: extension profiles are data and require migration for retyping."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from c1.interchange.jsonld import import_jsonld
from c1.model.diagnostics import ProfileError
from c1.model.profiles import ProfileRegistry, PropertyDefinition, compare_profiles

ROOT = Path(__file__).resolve().parents[3]
PROFILES = ROOT / "tests" / "fixtures" / "profiles"
EXAMPLE = PROFILES / "example-vehicle"
INCOMPATIBLE = PROFILES / "example-vehicle-v2-incompatible"
VEHICLE = "urn:c1:ns:example-vehicle#Vehicle"
WHEELS = "urn:c1:ns:example-vehicle#wheelCount"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"


def _code(error: pytest.ExceptionInfo[ProfileError]) -> str:
    return error.value.diagnostics[0].code


def test_data_only_extension_and_migration_proposal() -> None:
    registry = ProfileRegistry()
    registry.load(EXAMPLE)
    assert registry.primary_class([VEHICLE]).storage_name == "Vehicle"
    assert registry.classes[VEHICLE].properties[WHEELS].ranges == (XSD_INTEGER,)
    assert "urn:c1:ns:example-vehicle:context:1.0.0" in registry.contexts
    assert any(registry.shapes.subjects())
    fixture = json.loads((EXAMPLE / "vehicle.jsonld").read_text())
    assert len(import_jsonld(fixture, registry).records) == 1

    updated = ProfileRegistry()
    updated.load(INCOMPATIBLE)
    diagnostics = compare_profiles(
        registry.profiles["example-vehicle"], updated.profiles["example-vehicle"]
    )
    assert any(d.code == "C1-PR-004" and WHEELS in d.path for d in diagnostics)
    assert any("stored values" in d.message for d in diagnostics)
    assert not any(
        "vehicle" in path.read_text().lower() for path in (ROOT / "src" / "c1").rglob("*.py")
    )


def test_compatibility_distinguishes_additive_and_narrowed_changes() -> None:
    optional = "urn:c1:ns:example-vehicle#registrationCode"
    before = ProfileRegistry()
    before.load(EXAMPLE)
    original = before.profiles["example-vehicle"]
    prop = PropertyDefinition(
        "registrationCode", ("http://www.w3.org/2001/XMLSchema#string",), 0, 1
    )
    cls = original.classes[VEHICLE]
    added = replace(cls, properties={**cls.properties, optional: prop})
    updated = replace(
        original,
        version="1.1.0",
        classes={VEHICLE: added},
        property_constraints={
            **original.property_constraints,
            f"{VEHICLE} {optional}": (("pattern", "^[A-Z]"),),
        },
    )
    additive = compare_profiles(original, updated)
    assert any(d.code == "C1-PR-005" and optional in d.path for d in additive)
    assert not any(d.code == "C1-PR-004" for d in additive)

    required = replace(
        updated,
        classes={
            VEHICLE: replace(
                added, properties={**added.properties, optional: replace(prop, min_count=1)}
            )
        },
    )
    migration = compare_profiles(original, required)
    assert any(d.code == "C1-PR-004" and optional in d.path for d in migration)


def test_manifest_rejects_hooks_and_unsafe_paths_without_partial_load(tmp_path: Path) -> None:
    bad = tmp_path / "profile"
    shutil.copytree(EXAMPLE, bad)
    manifest_path = bad / "profile.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["validator_hook"] = "module:callable"
    manifest_path.write_text(json.dumps(manifest))
    registry = ProfileRegistry()
    old_classes = set(registry.classes)
    with pytest.raises(ProfileError) as error:
        registry.load(bad)
    assert _code(error) == "C1-PR-001"
    assert set(registry.classes) == old_classes

    del manifest["validator_hook"]
    manifest["context"] = "../../remote.jsonld"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ProfileError) as error:
        registry.load(bad)
    assert _code(error) == "C1-PR-001"


def test_profile_rejects_remote_context_and_unsupported_shacl(tmp_path: Path) -> None:
    bad = tmp_path / "profile"
    shutil.copytree(EXAMPLE, bad)
    context_path = bad / "context.jsonld"
    context = json.loads(context_path.read_text())
    context["@context"]["remote"] = {"@import": "https://example.invalid/context.jsonld"}
    context_path.write_text(json.dumps(context))
    with pytest.raises(ProfileError) as error:
        ProfileRegistry().load(bad)
    assert _code(error) == "C1-PR-002"

    context["@context"].pop("remote")
    context["@context"]["label"] = "urn:attacker:label"
    context_path.write_text(json.dumps(context))
    with pytest.raises(ProfileError) as error:
        ProfileRegistry().load(bad)
    assert _code(error) == "C1-PR-002"

    shutil.copyfile(EXAMPLE / "context.jsonld", context_path)
    shape_path = bad / "shapes.ttl"
    shape_path.write_text(
        shape_path.read_text()
        + "\n<urn:test:s> <http://www.w3.org/ns/shacl#sparql> <urn:test:q> .\n"
    )
    with pytest.raises(ProfileError) as error:
        ProfileRegistry().load(bad)
    assert _code(error) == "C1-PR-003"


def test_shape_must_match_manifest_before_profile_becomes_visible(tmp_path: Path) -> None:
    bad = tmp_path / "profile"
    shutil.copytree(EXAMPLE, bad)
    shape_path = bad / "shapes.ttl"
    shape_path.write_text(
        shape_path.read_text().replace(
            "sh:path <urn:c1:ns:example-vehicle#wheelCount> ; sh:minCount 1",
            "sh:path <urn:c1:ns:example-vehicle#wheelCount> ; sh:minCount 0",
        )
    )
    registry = ProfileRegistry()
    with pytest.raises(ProfileError) as error:
        registry.load(bad)
    assert _code(error) == "C1-PR-003"
    assert VEHICLE not in registry.classes


def test_new_enum_restriction_requires_migration() -> None:
    registry = ProfileRegistry()
    registry.load(EXAMPLE)
    original = registry.profiles["example-vehicle"]
    cls = original.classes[VEHICLE]
    predicate = "urn:c1:ns:example-vehicle#wheelCount"
    unrestricted = cls.properties[predicate]
    narrowed = replace(unrestricted, enum=("4",))
    updated = replace(
        original,
        classes={VEHICLE: replace(cls, properties={**cls.properties, predicate: narrowed})},
    )
    diagnostics = compare_profiles(original, updated)
    assert any(d.code == "C1-PR-004" and predicate in d.path for d in diagnostics)


@pytest.mark.parametrize(
    ("predicate", "constraint", "mutate_fixture"),
    [
        (
            WHEELS,
            'sh:hasValue "4"^^<http://www.w3.org/2001/XMLSchema#integer>',
            "wheel_count_three",
        ),
        (
            "http://www.w3.org/2004/02/skos/core#prefLabel",
            'sh:pattern "^Other"',
            "none",
        ),
        (
            "http://www.w3.org/2004/02/skos/core#prefLabel",
            'sh:languageIn ( "de" )',
            "none",
        ),
    ],
)
def test_shacl_only_narrowing_requires_migration(
    tmp_path: Path, predicate: str, constraint: str, mutate_fixture: str
) -> None:
    old = ProfileRegistry()
    old.load(EXAMPLE)
    fixture = json.loads((EXAMPLE / "vehicle.jsonld").read_text())
    if mutate_fixture == "wheel_count_three":
        fixture["@graph"][0]["wheelCount"]["@value"] = "3"
    assert len(import_jsonld(fixture, old).records) == 1

    new_dir = tmp_path / "profile"
    shutil.copytree(EXAMPLE, new_dir)
    shape_path = new_dir / "shapes.ttl"
    lines = shape_path.read_text().splitlines()
    matching = [index for index, line in enumerate(lines) if f"sh:path <{predicate}>" in line]
    assert len(matching) == 1
    index = matching[0]
    before, closing = lines[index].rsplit(" ]", 1)
    lines[index] = before + f" ; {constraint} ]" + closing
    shape_path.write_text("\n".join(lines) + "\n")
    manifest_path = new_dir / "profile.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "1.1.0"
    manifest_path.write_text(json.dumps(manifest))

    new = ProfileRegistry()
    new.load(new_dir)
    diagnostics = compare_profiles(old.profiles["example-vehicle"], new.profiles["example-vehicle"])
    assert any(d.code == "C1-PR-004" and predicate in d.path for d in diagnostics)
    with pytest.raises(ProfileError):
        import_jsonld(fixture, new)


def test_same_context_id_changed_content_requires_migration(tmp_path: Path) -> None:
    old = ProfileRegistry()
    old.load(EXAMPLE)
    new_dir = tmp_path / "profile"
    shutil.copytree(EXAMPLE, new_dir)
    context_path = new_dir / "context.jsonld"
    context = json.loads(context_path.read_text())
    context["@context"]["displayName"] = "http://www.w3.org/2004/02/skos/core#prefLabel"
    context_path.write_text(json.dumps(context))
    new = ProfileRegistry()
    new.load(new_dir)
    assert old.profiles["example-vehicle"].context_id == new.profiles["example-vehicle"].context_id
    assert (
        old.profiles["example-vehicle"].context_fingerprint
        != new.profiles["example-vehicle"].context_fingerprint
    )
    diagnostics = compare_profiles(old.profiles["example-vehicle"], new.profiles["example-vehicle"])
    assert any(d.code == "C1-PR-004" and "context" in d.message for d in diagnostics)
