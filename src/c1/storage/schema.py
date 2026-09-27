"""TerminusDB schema generation and guarded profile installation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileDefinition, ProfileRegistry
from c1.storage.mapping import _value_kind, installed_profile_iri, record_to_document
from c1.storage.terminus import StorageError

if TYPE_CHECKING:
    from c1.storage.terminus import Terminus

_DEFAULT_BASE = "terminusdb:///data/"
_DEFAULT_SCHEMA = "terminusdb:///schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_CORE = "urn:c1:ns:core#"


def _optional(name: str) -> dict[str, str]:
    return {"@type": "Optional", "@class": name}


def _set(name: str) -> dict[str, str]:
    return {"@type": "Set", "@class": name}


def _embedded_classes() -> list[dict[str, Any]]:
    """Literal values retain lexical identity; numeric/date fields are projections."""
    literal: dict[str, Any] = {
        "@type": "Class",
        "@id": "LiteralValue",
        "@key": {"@type": "Random"},
        "@subdocument": [],
        "lexical": "xsd:string",
        "datatype": "xsd:string",
        "language": _optional("xsd:string"),
        "value_integer": _optional("xsd:integer"),
        "value_decimal": _optional("xsd:decimal"),
        "value_boolean": _optional("xsd:boolean"),
        "value_double": _optional("xsd:double"),
        "value_earliest": _optional("xsd:dateTime"),
        "value_latest": _optional("xsd:dateTime"),
        "timezone_unknown": _optional("xsd:boolean"),
        "projection_status": _optional("xsd:string"),
    }
    value: dict[str, Any] = {
        "@type": "Class",
        "@id": "Value",
        "@key": {"@type": "Random"},
        "@subdocument": [],
        "iri": _optional("xsd:string"),
        "literal": _optional("LiteralValue"),
    }
    return [literal, value]


def profile_digest(profile: ProfileDefinition) -> str:
    """Pin the manifest, bundled context, and SHACL-only constraints together."""
    canonical = json.dumps(asdict(profile), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _class_schema(
    definition: ClassDefinition, profile_name: str, version: str, digest: str
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "@type": "Class",
        "@id": definition.storage_name,
        "@key": {"@type": definition.key_strategy},
        "@documentation": {"@comment": f"C1 profile {profile_name} {version} sha256:{digest}"},
        "canonical_iri": "xsd:string",
        "types": _set("xsd:string"),
    }
    for _predicate, prop in sorted(definition.properties.items()):
        kind = _value_kind(prop)
        field_type = (
            "xsd:string" if kind == "iri" else ("Value" if kind == "mixed" else "LiteralValue")
        )
        if prop.max_count == 1:
            value[prop.name] = field_type if prop.min_count else _optional(field_type)
        else:
            value[prop.name] = _set(field_type)
    return value


def generated_classes(registry: ProfileRegistry, profile_name: str) -> list[dict[str, Any]]:
    """Generate only declared classes; a profile contains data, never Python hooks."""
    profile = registry.profiles.get(profile_name)
    if profile is None:
        raise StorageError("C1-ST-006", "profile is not registered")
    names = [item.storage_name for item in registry.classes.values()]
    if len(names) != len(set(names)):
        raise StorageError("C1-ST-006", "profiles reuse a backend class name")
    digest = profile_digest(profile)
    return [
        _class_schema(definition, profile.name, profile.version, digest)
        for _iri, definition in sorted(profile.classes.items())
    ]


def generated_core_schema(registry: ProfileRegistry) -> list[dict[str, Any]]:
    """The checked-in schema used for fresh, empty knowledge databases."""
    profile = registry.profiles.get("core")
    if profile is None:
        raise StorageError("C1-ST-006", "core profile is not registered")
    context = {
        "@type": "@context",
        "@base": _DEFAULT_BASE,
        "@schema": _DEFAULT_SCHEMA,
        "xsd": _XSD,
        "rdf": _RDF,
        "@documentation": {
            "@title": f"C1 core {profile.version}",
            "@description": (
                "C1 core knowledge storage schema; public vocabulary uses urn:c1:ns:core#; "
                f"manifest sha256:{profile_digest(profile)}"
            ),
        },
    }
    return [context, *_embedded_classes(), *generated_classes(registry, "core")]


def _profile_marker(registry: ProfileRegistry, profile_name: str) -> NodeRecord:
    profile = registry.profiles[profile_name]
    return NodeRecord(
        id=installed_profile_iri(profile_name),
        types=[_CORE + "SchemaProfile"],
        properties={
            _CORE + "profileName": [LiteralValue(lexical=profile.name, datatype=_XSD + "string")],
            _CORE + "profileVersion": [
                LiteralValue(lexical=profile.version, datatype=_XSD + "string")
            ],
            _CORE + "contentDigest": [
                LiteralValue(lexical=profile_digest(profile), datatype=_XSD + "string")
            ],
        },
    )


def _context_document(schema: list[dict[str, Any]]) -> dict[str, Any]:
    contexts = [item for item in schema if item.get("@type") == "@context"]
    if len(contexts) != 1:
        raise StorageError("C1-ST-006", "backend schema context is missing or ambiguous")
    return contexts[0]


def _class_index(schema: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    classes = [item for item in schema if item.get("@type") == "Class"]
    result = {str(item.get("@id")): item for item in classes}
    if len(result) != len(classes):
        raise StorageError("C1-ST-006", "backend schema has duplicate class names")
    return result


def _assert_authority(schema: list[dict[str, Any]], registry: ProfileRegistry) -> None:
    context = _context_document(schema)
    if context != generated_core_schema(registry)[0]:
        raise StorageError("C1-ST-006", "installed core schema authority does not match")
    classes = _class_index(schema)
    for expected in _embedded_classes():
        if classes.get(expected["@id"]) != expected:
            raise StorageError("C1-ST-006", "embedded value schema differs from manifest")
    for name in registry.profiles:
        for expected in generated_classes(registry, name):
            actual = classes.get(expected["@id"])
            if actual != expected:
                raise StorageError("C1-ST-006", "installed profile class differs from manifest")


async def assert_installed_profiles(client: Terminus, registry: ProfileRegistry) -> None:
    """Require schema authority and its instance-graph projection to agree."""
    if "core" not in registry.profiles:
        raise StorageError("C1-ST-006", "core profile is not registered")
    schema = await client.schema_documents()
    _assert_authority(schema, registry)
    for name in registry.profiles:
        expected = _profile_marker(registry, name)
        marker_id = record_to_document(expected, registry, client.config.instance_base)["@id"]
        stored = await client.get(marker_id)
        if stored is None:
            raise StorageError("C1-ST-006", "installed profile marker is missing")
        from c1.storage.mapping import document_to_record

        if document_to_record(stored, registry) != expected:
            raise StorageError("C1-ST-006", "installed profile marker does not match schema")


async def install_core_profile(client: Terminus, registry: ProfileRegistry) -> str:
    """Install the core schema only after an empty-instance check and head CAS."""
    if "core" not in registry.profiles:
        raise StorageError("C1-ST-006", "core profile is not registered")
    base = await client.head()
    instances = await client.documents()
    if instances:
        raise StorageError("C1-ST-001", "core schema installation requires an empty database")
    existing = await client.schema_documents()
    if len(existing) != 1 or existing[0] != {
        "@type": "@context",
        "@base": _DEFAULT_BASE,
        "@schema": _DEFAULT_SCHEMA,
    }:
        raise StorageError("C1-ST-001", "core schema installation requires a fresh database")
    schema_head = await client._insert(
        generated_core_schema(registry),
        expected_head=base,
        message="Install C1 core profile schema",
        graph_type="schema",
        full_replace=True,
    )
    marker = record_to_document(
        _profile_marker(registry, "core"), registry, client.config.instance_base
    )
    return await client._insert(
        [marker], expected_head=schema_head, message="Project C1 core profile version"
    )


async def install_additive_profile(
    client: Terminus, registry: ProfileRegistry, profile_name: str
) -> str:
    """Install only compatible new classes after checking the installed core."""
    if profile_name == "core" or profile_name not in registry.profiles:
        raise StorageError("C1-ST-006", "expected a registered extension profile")
    profile = registry.profiles[profile_name]
    if profile.requires_core != registry.profiles["core"].version:
        raise StorageError("C1-ST-006", "extension requires a different core profile version")
    base = await client.head()
    core_only = ProfileRegistry()
    if profile_digest(core_only.profiles["core"]) != profile_digest(registry.profiles["core"]):
        raise StorageError("C1-ST-006", "loaded core profile differs from installation baseline")
    await assert_installed_profiles(client, core_only)
    schema = await client.schema_documents()
    installed_classes = _class_index(schema)
    additions = generated_classes(registry, profile_name)
    if any(item["@id"] in installed_classes for item in additions):
        raise StorageError("C1-ST-006", "extension already exists; migration required")
    marker = record_to_document(
        _profile_marker(registry, profile_name), registry, client.config.instance_base
    )
    if await client.get(marker["@id"]) is not None:
        raise StorageError("C1-ST-006", "extension marker already exists; migration required")
    schema_head = await client._insert(
        additions,
        expected_head=base,
        message=f"Install C1 profile {profile_name} {profile.version}",
        graph_type="schema",
    )
    return await client._insert(
        [marker],
        expected_head=schema_head,
        message=f"Project C1 profile {profile_name} {profile.version}",
    )
