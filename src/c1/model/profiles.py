"""Versioned, data-only vocabulary profiles.

Profiles describe the accepted RDF classes and predicates. Loading a profile
does not execute code or resolve network resources.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from c1.model.diagnostics import Diagnostic, ProfileError, fail
from c1.model.ids import validate_iri
from c1.model.literals import SUPPORTED_DATATYPES

SH = Namespace("http://www.w3.org/ns/shacl#")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_NAME = re.compile(r"^[a-z][A-Za-z0-9-]*$")
_SCHEMA_KEYS = {"name", "version", "requires_core", "context", "shapes", "classes", "predicates"}
_CLASS_KEYS = {"storage_name", "kind", "key_strategy", "properties"}
_PROPERTY_KEYS = {"name", "ranges", "min_count", "max_count", "enum"}
_SHAPE_PREDICATES = {
    RDF.type,
    SH.targetClass,
    SH.property,
    SH.path,
    SH.minCount,
    SH.maxCount,
    SH.datatype,
    SH.nodeKind,
    SH["class"],
    SH["in"],
    SH.pattern,
    SH.languageIn,
    SH.hasValue,
    SH["or"],
    RDF.first,
    RDF.rest,
}
_SHAPE_TYPES = {SH.NodeShape, SH.PropertyShape}
_LIST_PREDICATES = {SH["in"], SH.languageIn, SH["or"]}
_RESERVED = {"software"}


@dataclass(frozen=True)
class PropertyDefinition:
    name: str
    ranges: tuple[str, ...]
    min_count: int = 0
    max_count: int | None = None
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassDefinition:
    iri: str
    storage_name: str
    kind: str
    key_strategy: str
    properties: dict[str, PropertyDefinition]


@dataclass(frozen=True)
class ProfileDefinition:
    name: str
    version: str
    requires_core: str | None
    context_id: str
    classes: dict[str, ClassDefinition]
    predicates: dict[str, PropertyDefinition]
    context_fingerprint: str = ""
    property_constraints: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)


def _object(value: object, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        fail("C1-PR-001", "Expected an object", path)
    unexpected = set(value) - keys
    if unexpected:
        fail("C1-PR-001", f"Unsupported profile keys: {sorted(unexpected)}", path)
    return value


def _iri(value: object, path: str) -> str:
    try:
        validate_iri(value)  # type: ignore[arg-type]
    except ProfileError:
        fail("C1-PR-001", "Expected a safe absolute IRI", path)
    assert isinstance(value, str)
    return value


def _range(value: object, path: str) -> str:
    if value == "@id":
        return "@id"
    return _iri(value, path)


def _local_filename(value: object, path: str, suffix: str) -> str:
    if not isinstance(value, str) or value != Path(value).name or not value.endswith(suffix):
        fail("C1-PR-001", "Expected a local profile filename", path)
    return value


def _property(value: object, path: str) -> PropertyDefinition:
    data = _object(value, path, _PROPERTY_KEYS)
    if not isinstance(data.get("name"), str) or not _NAME.fullmatch(data["name"]):
        fail("C1-PR-001", "Invalid storage property name", path)
    ranges = data.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        fail("C1-PR-001", "Property needs at least one range", path)
    parsed_ranges = tuple(_range(item, f"{path}/ranges") for item in ranges)
    if len(parsed_ranges) != len(set(parsed_ranges)):
        fail("C1-PR-001", "Duplicate property range", path)
    minimum = data.get("min_count", 0)
    maximum = data.get("max_count")
    if type(minimum) is not int or minimum < 0:
        fail("C1-PR-001", "Invalid min_count", path)
    if maximum is not None and (type(maximum) is not int or maximum < minimum):
        fail("C1-PR-001", "Invalid max_count", path)
    enum = data.get("enum", [])
    if not isinstance(enum, list) or any(not isinstance(item, str) for item in enum):
        fail("C1-PR-001", "Invalid enum", path)
    if len(enum) != len(set(enum)):
        fail("C1-PR-001", "Duplicate enum member", path)
    return PropertyDefinition(data["name"], parsed_ranges, minimum, maximum, tuple(enum))


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(code, f"Could not parse local profile file: {type(exc).__name__}", str(path))
    if not isinstance(value, dict):
        fail(code, "Profile file must be a JSON object", str(path))
    return value


def _validate_context(value: dict[str, Any], path: str) -> str:
    if set(value) != {"@id", "@context"}:
        fail("C1-PR-002", "Bundled context needs only @id and @context", path)
    context_id = _iri(value["@id"], path)
    definitions = value["@context"]
    if not isinstance(definitions, dict):
        fail("C1-PR-002", "Bundled @context must be an object", path)
    for term, definition in definitions.items():
        if not isinstance(term, str) or term.startswith("@"):
            fail("C1-PR-002", "Invalid context term", path)
        if isinstance(definition, str):
            if not definition or definition.startswith("@"):
                fail("C1-PR-002", "Invalid context term IRI", f"{path}/{term}")
        elif isinstance(definition, dict):
            if set(definition) - {"@id", "@type", "@container", "@language"}:
                fail("C1-PR-002", "Unsupported context term definition", f"{path}/{term}")
            if "@id" not in definition or not isinstance(definition["@id"], str):
                fail("C1-PR-002", "Term definition needs @id", f"{path}/{term}")
            if definition.get("@container") not in (None, "@set"):
                fail("C1-PR-002", "Only @set containers are supported", f"{path}/{term}")
            if definition.get("@type") not in (None, "@id", "@vocab"):
                fail("C1-PR-002", "Unsupported type coercion", f"{path}/{term}")
        else:
            fail("C1-PR-002", "Invalid context definition", f"{path}/{term}")
    return context_id


def _rdf_list(graph: Graph, head: URIRef | Any, path: str) -> list[Any]:
    values: list[Any] = []
    seen: set[Any] = set()
    cursor = head
    while cursor != RDF.nil:
        if cursor in seen:
            fail("C1-PR-003", "Cyclic SHACL list", path)
        seen.add(cursor)
        first = list(graph.objects(cursor, RDF.first))
        rest = list(graph.objects(cursor, RDF.rest))
        if len(first) != 1 or len(rest) != 1:
            fail("C1-PR-003", "Malformed SHACL list", path)
        values.append(first[0])
        cursor = rest[0]
    return values


def _validate_shapes(graph: Graph, path: str) -> None:
    for _subject, predicate, obj in graph:
        if predicate not in _SHAPE_PREDICATES:
            fail("C1-PR-003", f"Unsupported SHACL predicate {predicate}", path)
        if predicate == RDF.type and obj not in _SHAPE_TYPES:
            fail("C1-PR-003", f"Unsupported SHACL type {obj}", path)
        if predicate in {
            SH.targetClass,
            SH.path,
            SH.datatype,
            SH.nodeKind,
            SH["class"],
        } and not isinstance(obj, URIRef):
            fail("C1-PR-003", "SHACL constraint needs an IRI", path)
        if predicate in _LIST_PREDICATES:
            members = _rdf_list(graph, obj, path)
            if not members:
                fail("C1-PR-003", "Empty SHACL list", path)
            if predicate == SH["or"]:
                for item in members:
                    constraints = list(graph.predicate_objects(item))
                    if len(constraints) != 1 or constraints[0][0] not in {
                        SH.nodeKind,
                        SH.datatype,
                        SH["class"],
                    }:
                        fail("C1-PR-003", "Only node-kind/range alternatives are supported", path)
    for node in graph.subjects(RDF.type, SH.NodeShape):
        if len(list(graph.objects(node, SH.targetClass))) != 1:
            fail("C1-PR-003", "NodeShape needs one targetClass", path)
    for node in graph.objects(None, SH.property):
        if len(list(graph.objects(node, SH.path))) != 1:
            fail("C1-PR-003", "Property shape needs one simple path", path)
    for node in graph.subjects(SH.path, None):
        if node not in set(graph.objects(None, SH.property)):
            fail("C1-PR-003", "Orphan property shape", path)


def _shape_ranges(graph: Graph, node: Any, path: str) -> set[str]:
    single = list(graph.predicate_objects(node))
    direct = [
        (predicate, obj)
        for predicate, obj in single
        if predicate in {SH.datatype, SH.nodeKind, SH["class"]}
    ]
    alternatives = list(graph.objects(node, SH["or"]))
    if bool(direct) == bool(alternatives):
        fail("C1-PR-003", "Property shape needs one range expression", path)
    if alternatives:
        if len(alternatives) != 1:
            fail("C1-PR-003", "Multiple range alternatives", path)
        direct = []
        for item in _rdf_list(graph, alternatives[0], path):
            clauses = list(graph.predicate_objects(item))
            if len(clauses) != 1:
                fail("C1-PR-003", "Complex range alternative", path)
            direct.extend(clauses)
    if len(direct) != len(set(direct)):
        fail("C1-PR-003", "Duplicate range alternative", path)
    result: set[str] = set()
    for predicate, obj in direct:
        if predicate == SH.nodeKind:
            if obj == SH.IRI:
                result.add("@id")
            elif obj == SH.Literal:
                result.add(str(RDFS.Literal))
            else:
                fail("C1-PR-003", "Unsupported node kind", path)
        elif predicate in {SH.datatype, SH["class"]} and isinstance(obj, URIRef):
            result.add(str(obj))
        else:
            fail("C1-PR-003", "Unsupported range constraint", path)
    if len(result) != len(direct):
        fail("C1-PR-003", "Duplicate range alternative", path)
    return result


def _shape_count(graph: Graph, node: Any, predicate: URIRef, path: str) -> int | None:
    values = list(graph.objects(node, predicate))
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], Literal) or values[0].datatype != XSD.integer:
        fail("C1-PR-003", "Invalid SHACL cardinality", path)
    try:
        result = int(str(values[0]))
    except ValueError:
        fail("C1-PR-003", "Invalid SHACL cardinality", path)
    if result < 0:
        fail("C1-PR-003", "Negative SHACL cardinality", path)
    return result


def _validate_shape_manifest(graph: Graph, classes: dict[str, ClassDefinition], path: str) -> None:
    targets = set(graph.objects(None, SH.targetClass))
    if targets != {URIRef(iri) for iri in classes}:
        fail("C1-PR-003", "Shape targets disagree with profile classes", path)
    for iri, definition in classes.items():
        shapes = list(graph.subjects(SH.targetClass, URIRef(iri)))
        if len(shapes) != 1:
            fail("C1-PR-003", "Class needs exactly one shape", iri)
        properties: dict[str, Any] = {}
        for node in graph.objects(shapes[0], SH.property):
            predicates = list(graph.objects(node, SH.path))
            if len(predicates) != 1 or str(predicates[0]) in properties:
                fail("C1-PR-003", "Duplicate or missing SHACL property path", iri)
            properties[str(predicates[0])] = node
        if set(properties) != set(definition.properties):
            fail("C1-PR-003", "Shape properties disagree with manifest", iri)
        for predicate, declared in definition.properties.items():
            node = properties[predicate]
            minimum = _shape_count(graph, node, SH.minCount, predicate)
            maximum = _shape_count(graph, node, SH.maxCount, predicate)
            if (minimum or 0) != declared.min_count or maximum != declared.max_count:
                fail("C1-PR-003", "Shape cardinality disagrees with manifest", predicate)
            if _shape_ranges(graph, node, predicate) != set(declared.ranges):
                fail("C1-PR-003", "Shape range disagrees with manifest", predicate)
            allowed = list(graph.objects(node, SH["in"]))
            if len(allowed) > 1:
                fail("C1-PR-003", "Multiple enum constraints", predicate)
            enum = _rdf_list(graph, allowed[0], predicate) if allowed else []
            if {str(value) for value in enum} != set(declared.enum):
                fail("C1-PR-003", "Shape enum disagrees with manifest", predicate)
            if any(
                not isinstance(value, Literal) or value.datatype != XSD.string for value in enum
            ):
                fail("C1-PR-003", "Shape enum values need xsd:string", predicate)


def _term_signature(value: Any, path: str) -> str:
    if isinstance(value, URIRef):
        return json.dumps(["iri", str(value)], separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, Literal):
        return json.dumps(
            ["literal", str(value), str(value.datatype or ""), value.language or ""],
            separators=(",", ":"),
            ensure_ascii=False,
        )
    fail("C1-PR-003", "Blank-node constraint value is unsupported", path)


def _supplemental_constraints(
    graph: Graph, classes: dict[str, ClassDefinition], path: str
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Capture only the shape clauses not represented in the manifest fields."""

    result: dict[str, tuple[tuple[str, str], ...]] = {}
    for class_iri, definition in classes.items():
        shape = next(graph.subjects(SH.targetClass, URIRef(class_iri)))
        for node in graph.objects(shape, SH.property):
            predicate = str(next(graph.objects(node, SH.path)))
            assert predicate in definition.properties
            clauses: list[tuple[str, str]] = []
            for obj in graph.objects(node, SH.pattern):
                if (
                    not isinstance(obj, Literal)
                    or obj.language
                    or obj.datatype
                    not in (
                        None,
                        XSD.string,
                    )
                ):
                    fail("C1-PR-003", "Pattern must be a string literal", path)
                try:
                    re.compile(str(obj))
                except re.error:
                    fail("C1-PR-003", "Invalid SHACL pattern", path)
                clauses.append(("pattern", str(obj)))
            for obj in graph.objects(node, SH.hasValue):
                clauses.append(("hasValue", _term_signature(obj, path)))
            language_lists = list(graph.objects(node, SH.languageIn))
            if len(language_lists) > 1:
                fail("C1-PR-003", "Multiple languageIn constraints", path)
            if language_lists:
                languages = _rdf_list(graph, language_lists[0], path)
                if any(
                    not isinstance(value, Literal)
                    or value.language
                    or value.datatype not in (None, XSD.string)
                    for value in languages
                ):
                    fail("C1-PR-003", "languageIn needs string literals", path)
                clauses.append(
                    (
                        "languageIn",
                        json.dumps(
                            sorted(str(value) for value in languages),
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    )
                )
            if clauses:
                result[f"{class_iri} {predicate}"] = tuple(sorted(clauses))
    return result


class ProfileRegistry:
    """Loaded profile data; all source paths must be explicitly local."""

    def __init__(self, *, load_core: bool = True) -> None:
        self.classes: dict[str, ClassDefinition] = {}
        self.predicates: dict[str, PropertyDefinition] = {}
        self.contexts: dict[str, dict[str, Any]] = {}
        self.shapes = Graph()
        self.profiles: dict[str, ProfileDefinition] = {}
        if load_core:
            package_profile = Path(__file__).resolve().parents[1] / "profiles" / "core"
            repository_profile = Path(__file__).resolve().parents[3] / "profiles" / "core"
            core_profile = package_profile if package_profile.is_dir() else repository_profile
            self.load(core_profile)
            for extension in sorted(core_profile.parent.iterdir()):
                if extension.is_symlink():
                    fail("C1-PR-001", "Profile directory symlink is unsupported", str(extension))
                if (
                    extension.is_dir()
                    and extension != core_profile
                    and (extension / "profile.json").is_file()
                ):
                    self.load(extension)

    def primary_class(self, types: list[str]) -> ClassDefinition:
        matches = [self.classes[iri] for iri in types if iri in self.classes]
        if len(matches) != 1:
            fail("C1-PR-001", "Exactly one registered primary class is required", "/@type")
        return matches[0]

    def load(self, path: Path) -> None:
        if path.is_symlink():
            fail("C1-PR-001", "Profile path symlink is unsupported", str(path))
        if not path.is_dir() and (not path.is_file() or path.name != "profile.json"):
            fail("C1-PR-001", "Expected a profile directory or profile.json", str(path))
        directory = path if path.is_dir() else path.parent
        manifest_path = directory / "profile.json"
        if manifest_path.is_symlink():
            fail("C1-PR-001", "Manifest symlink is unsupported", str(manifest_path))
        manifest = _object(_read_json(manifest_path, "C1-PR-001"), str(manifest_path), _SCHEMA_KEYS)
        name = manifest.get("name")
        version = manifest.get("version")
        requires_core = manifest.get("requires_core")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            fail("C1-PR-001", "Invalid profile name", str(manifest_path))
        if name in _RESERVED:
            fail("C1-PR-001", "Reserved profile name", str(manifest_path))
        if not isinstance(version, str) or not _SEMVER.fullmatch(version):
            fail("C1-PR-001", "Profile version must be semver", str(manifest_path))
        if requires_core is not None and (
            not isinstance(requires_core, str) or not _SEMVER.fullmatch(requires_core)
        ):
            fail("C1-PR-001", "Invalid requires_core version", str(manifest_path))
        if name != "core" and (
            "core" not in self.profiles or requires_core != self.profiles["core"].version
        ):
            fail("C1-PR-001", "Extension requires the loaded core version", str(manifest_path))
        if name == "core" and requires_core is not None:
            fail("C1-PR-001", "Core must not require itself", str(manifest_path))
        if name in self.profiles:
            fail("C1-PR-001", "Profile already loaded", str(manifest_path))
        context_file = _local_filename(manifest.get("context"), "context", ".jsonld")
        shapes_file = _local_filename(manifest.get("shapes"), "shapes", ".ttl")
        context_path = directory / context_file
        if context_path.is_symlink():
            fail("C1-PR-002", "Context symlink is unsupported", str(context_path))
        context = _read_json(context_path, "C1-PR-002")
        context_id = _validate_context(context, str(context_path))
        if context_id in self.contexts:
            fail("C1-PR-002", "Context identifier already loaded", str(context_path))
        for existing_context in self.contexts.values():
            for term, definition in context["@context"].items():
                if term in existing_context["@context"] and (
                    definition != existing_context["@context"][term]
                ):
                    fail("C1-PR-002", "Profile redefines a registered context term", term)
        shape_path = directory / shapes_file
        if shape_path.is_symlink():
            fail("C1-PR-003", "Shape symlink is unsupported", str(shape_path))
        graph = Graph()
        try:
            graph.parse(shape_path, format="turtle")
        except Exception as exc:
            fail("C1-PR-003", f"Invalid local shapes: {type(exc).__name__}", str(shape_path))
        _validate_shapes(graph, str(shape_path))
        raw_classes = manifest.get("classes")
        raw_predicates = manifest.get("predicates")
        if not isinstance(raw_classes, dict) or not isinstance(raw_predicates, dict):
            fail("C1-PR-001", "Classes and predicates must be objects", str(manifest_path))
        classes: dict[str, ClassDefinition] = {}
        for iri, raw in raw_classes.items():
            class_iri = _iri(iri, "/classes")
            data = _object(raw, f"/classes/{iri}", _CLASS_KEYS)
            storage_name = data.get("storage_name")
            kind = data.get("kind")
            key_strategy = data.get("key_strategy", "Random")
            if not isinstance(storage_name, str) or not re.fullmatch(
                r"[A-Z][A-Za-z0-9]*", storage_name
            ):
                fail("C1-PR-001", "Invalid storage class name", f"/classes/{iri}")
            if kind not in {"record", "auxiliary", "workflow"} or key_strategy not in {
                "Random",
                "ValueHash",
            }:
                fail("C1-PR-001", "Invalid class kind or key strategy", f"/classes/{iri}")
            properties = data.get("properties")
            if not isinstance(properties, dict):
                fail("C1-PR-001", "Class properties must be an object", f"/classes/{iri}")
            parsed = {
                _iri(k, f"/classes/{iri}/properties"): _property(
                    v, f"/classes/{iri}/properties/{k}"
                )
                for k, v in properties.items()
            }
            if len({prop.name for prop in parsed.values()}) != len(parsed):
                fail("C1-PR-001", "Duplicate storage property name", f"/classes/{iri}")
            classes[class_iri] = ClassDefinition(
                class_iri, storage_name, kind, key_strategy, parsed
            )
        _validate_shape_manifest(graph, classes, str(shape_path))
        property_constraints = _supplemental_constraints(graph, classes, str(shape_path))
        predicates = {
            _iri(k, "/predicates"): _property(v, f"/predicates/{k}")
            for k, v in raw_predicates.items()
        }
        known_ranges = set(SUPPORTED_DATATYPES) | {
            "@id",
            str(RDFS.Literal),
            *classes,
            *self.classes,
        }
        for definition in classes.values():
            for iri, prop in definition.properties.items():
                if set(prop.ranges) - known_ranges:
                    fail("C1-PR-001", "Property uses an unsupported range", iri)
        for iri, prop in predicates.items():
            if set(prop.ranges) - known_ranges:
                fail("C1-PR-001", "Predicate uses an unsupported range", iri)
        for definition in classes.values():
            for iri, prop in definition.properties.items():
                if iri in predicates:
                    previous = predicates[iri]
                    if previous.name != prop.name:
                        fail("C1-PR-001", "Predicate has conflicting storage names", iri)
                    predicates[iri] = PropertyDefinition(
                        previous.name,
                        tuple(dict.fromkeys((*previous.ranges, *prop.ranges))),
                        0,
                        None,
                        tuple(dict.fromkeys((*previous.enum, *prop.enum))),
                    )
                else:
                    predicates[iri] = PropertyDefinition(prop.name, prop.ranges, 0, None, prop.enum)
        if set(classes) & set(self.classes):
            fail("C1-PR-001", "Profile redefines an existing class", str(manifest_path))
        for iri in set(predicates) & set(self.predicates):
            existing = self.predicates[iri]
            incoming = predicates[iri]
            if existing.name != incoming.name or not set(incoming.ranges) <= set(existing.ranges):
                fail("C1-PR-001", "Profile redefines an existing predicate range", iri)
            # Shared vocabulary predicates retain the core's broad declaration;
            # each class retains its own cardinality and range constraints.
            del predicates[iri]
        profile_definition = ProfileDefinition(
            name,
            version,
            requires_core,
            context_id,
            classes,
            predicates,
            hashlib.sha256(
                json.dumps(
                    context, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
            property_constraints,
        )
        self.classes.update(classes)
        self.predicates.update(predicates)
        self.contexts[context_id] = context
        self.shapes += graph
        self.profiles[name] = profile_definition


def compare_profiles(old: ProfileDefinition, new: ProfileDefinition) -> list[Diagnostic]:
    """Describe additive changes and migration checks; never perform a migration."""

    if old.name != new.name:
        return [
            Diagnostic(
                code="C1-PR-005",
                severity="info",
                path=new.name,
                message=f"Additive new profile {new.name}",
            )
        ]
    result: list[Diagnostic] = []

    def add(path: str, message: str, *, migration: bool = False) -> None:
        result.append(
            Diagnostic(
                code="C1-PR-004" if migration else "C1-PR-005",
                severity="error" if migration else "info",
                path=path,
                message=message,
            )
        )

    if old.requires_core != new.requires_core:
        add(
            new.name,
            "MigrationRequired: core requirement changed; check installed core version",
            migration=True,
        )
    if old.context_id != new.context_id:
        add(
            new.name,
            "MigrationRequired: context identifier changed; check serialized data mappings",
            migration=True,
        )
    elif old.context_fingerprint != new.context_fingerprint:
        add(
            new.name,
            "MigrationRequired: bundled context changed under the same identifier; "
            "check serialized data mappings",
            migration=True,
        )

    for iri, original in old.classes.items():
        updated = new.classes.get(iri)
        if updated is None:
            add(
                iri,
                f"MigrationRequired: class {iri} removed; check stored instances",
                migration=True,
            )
            continue
        if (original.storage_name, original.key_strategy, original.kind) != (
            updated.storage_name,
            updated.key_strategy,
            updated.kind,
        ):
            add(
                iri,
                f"MigrationRequired: class {iri} storage identity changed; "
                "check stored IDs and references",
                migration=True,
            )
        _compare_properties(original.properties, updated.properties, iri, add)
        for predicate in original.properties.keys() & updated.properties.keys():
            key = f"{iri} {predicate}"
            if old.property_constraints.get(key, ()) != new.property_constraints.get(key, ()):
                add(
                    key,
                    "MigrationRequired: SHACL supplemental constraint changed; "
                    "check stored values against the new shape",
                    migration=True,
                )
    for iri in new.classes.keys() - old.classes.keys():
        add(iri, f"Additive class {iri}")
    _compare_properties(old.predicates, new.predicates, "predicate", add)
    return result


def _compare_properties(
    old: dict[str, PropertyDefinition],
    new: dict[str, PropertyDefinition],
    owner: str,
    add: Any,
) -> None:
    for iri, original in old.items():
        path = f"{owner}/{iri}"
        updated = new.get(iri)
        if updated is None:
            add(
                path,
                f"MigrationRequired: predicate {iri} removed from {owner}; check stored values",
                migration=True,
            )
            continue
        incompatible = (
            original.name != updated.name
            or not set(original.ranges) <= set(updated.ranges)
            or updated.min_count > original.min_count
            or (
                updated.max_count is not None
                and (original.max_count is None or updated.max_count < original.max_count)
            )
            or (
                bool(updated.enum)
                and (not original.enum or not set(original.enum) <= set(updated.enum))
            )
        )
        if incompatible:
            add(
                path,
                f"MigrationRequired: predicate {iri} narrowed/retyped in {owner}; "
                "check stored values and cardinality",
                migration=True,
            )
        elif original != updated:
            add(path, f"Additive predicate widening {iri} in {owner}")
    for iri, prop in new.items():
        if iri not in old:
            path = f"{owner}/{iri}"
            if prop.min_count:
                add(
                    path,
                    f"MigrationRequired: new required predicate {iri} in {owner}; "
                    "check stored instances",
                    migration=True,
                )
            else:
                add(path, f"Additive optional predicate {iri} in {owner}")
