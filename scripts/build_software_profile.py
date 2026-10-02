"""Generate or check the data-only `software` profile (M08 D1).

The manifest, bundled JSON-LD context, and SHACL shapes are derived from one
declaration below so the three files cannot drift. Entity-kind classes reuse
the core Entity template and its supplemental constraints; record-kind classes
get shapes generated from their declared properties.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "profiles/available/software"
# The M04 catalog tests keep an identical copy of every bundled profile.
TARGETS = (TARGET, ROOT / "tests/fixtures/profiles/software")

C1 = "urn:c1:ns:core#"
S = "urn:c1:ns:software#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
PROV = "http://www.w3.org/ns/prov#"
DCT = "http://purl.org/dc/terms/"

# 1.1.0 adds the M09 test-development predicates; 1.2.0 adds M10 support
# aspects and the minimal negative applicability declaration. There is no in-place
# upgrade path; development databases are reinstalled (owner, 2026-09-29).
VERSION = "1.2.0"

STRING = XSD + "string"
INTEGER = XSD + "integer"
STAMP = XSD + "dateTimeStamp"

ENTITY_CLASSES: dict[str, dict[str, Any]] = {
    "SoftwareProduct": {"storage": "SwProduct", "extra": {}},
    "CodeRepository": {
        "storage": "SwRepository",
        "extra": {"repositoryKey": ([STRING], 1, 1, [])},
    },
    "SoftwareRelease": {
        "storage": "SwRelease",
        "extra": {"releaseVersion": ([STRING], 1, 1, [])},
    },
    "SourceSnapshot": {
        "storage": "SwSnapshot",
        "extra": {
            "repositoryRef": ([S + "CodeRepository"], 1, 1, []),
            "commitId": ([STRING], 1, 1, []),
            "treeId": ([STRING], 0, 1, []),
        },
    },
    "Capability": {"storage": "SwCapability", "extra": {}},
    "CodeSymbol": {
        "storage": "SwSymbol",
        "extra": {
            "repositoryRef": ([S + "CodeRepository"], 1, 1, []),
            "scipScheme": ([STRING], 1, 1, []),
            "packageManager": ([STRING], 1, 1, []),
            "packageName": ([STRING], 1, 1, []),
            "descriptors": ([STRING], 1, 1, []),
        },
    },
    "InterfaceOperation": {
        # A logical operation identity (provider product + operationId); each
        # contract version that specifies it is linked by `specifiedIn`.
        "storage": "SwOperation",
        "extra": {
            "providerRef": ([S + "SoftwareProduct"], 1, 1, []),
            "operationId": ([STRING], 1, 1, []),
            "httpMethod": (
                [STRING],
                1,
                1,
                ["delete", "get", "head", "options", "patch", "post", "put", "trace"],
            ),
            "pathTemplate": ([STRING], 1, 1, []),
        },
    },
    "TestCase": {"storage": "SwTestCase", "extra": {}},
    # M10 D2: a declared support aspect (retry, timeout, configuration, ...).
    "Aspect": {"storage": "SwAspect", "extra": {}},
}

ROLES = [
    "definition",
    "forward-definition",
    "generated",
    "import",
    "read-access",
    "reference",
    "test",
    "write-access",
]

RECORD_CLASSES: dict[str, dict[str, Any]] = {
    "SymbolOccurrence": {
        "storage": "SwOccurrence",
        "properties": {
            S + "symbolRef": ([S + "CodeSymbol"], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, 1, []),
            S + "fileRef": ([C1 + "Document"], 1, 1, []),
            S + "partRef": ([C1 + "DocumentPart"], 0, 1, []),
            S + "role": ([STRING], 1, None, ROLES),
            S + "startLine": ([INTEGER], 1, 1, []),
            S + "startCharacter": ([INTEGER], 1, 1, []),
            S + "endLine": ([INTEGER], 1, 1, []),
            S + "endCharacter": ([INTEGER], 1, 1, []),
            S + "positionEncoding": ([STRING], 1, 1, ["unspecified", "utf-16", "utf-32", "utf-8"]),
            PROV + "wasGeneratedBy": (["@id"], 0, 1, []),
        },
    },
    "TestRun": {
        "storage": "SwTestRun",
        "properties": {
            S + "testCaseRef": ([S + "TestCase"], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, None, []),
            S + "configurationRef": ([S + "Configuration"], 0, 1, []),
            S + "result": ([STRING], 1, 1, ["error", "fail", "pass", "skipped"]),
            S + "integrationMode": ([STRING], 1, 1, ["live", "mocked", "unknown"]),
            S + "mockedProductRef": ([S + "SoftwareProduct"], 0, None, []),
            S + "startedAt": ([STAMP], 0, 1, []),
            S + "endedAt": ([STAMP], 0, 1, []),
            S + "reportRef": ([C1 + "Document"], 0, 1, []),
            PROV + "wasGeneratedBy": (["@id"], 0, 1, []),
        },
    },
    "Configuration": {
        "storage": "SwConfiguration",
        "properties": {
            S + "configurationName": ([STRING], 1, 1, []),
            S + "parameter": ([STRING], 0, None, []),
            S + "configurationDigest": ([STRING], 1, 1, []),
        },
    },
    "TargetSet": {
        "storage": "SwTargetSet",
        "properties": {
            S + "targetLabel": ([STRING], 1, 1, []),
            S + "memberSnapshot": ([S + "SourceSnapshot"], 1, None, []),
            S + "memberContract": ([C1 + "Document"], 0, None, []),
            S + "memberConfiguration": ([S + "Configuration"], 0, None, []),
        },
    },
    "BranchObservation": {
        "storage": "SwBranchObservation",
        "properties": {
            S + "repositoryRef": ([S + "CodeRepository"], 1, 1, []),
            S + "branchName": ([STRING], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, 1, []),
            S + "branchObservedAt": ([STAMP], 1, 1, []),
        },
    },
    "ImportCoverage": {
        "storage": "SwImportCoverage",
        "properties": {
            S + "activityRef": ([PROV + "Activity"], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, 1, []),
            S + "importMethod": (
                [STRING],
                1,
                1,
                [
                    "ast-calls",
                    "docs",
                    "junit-runs",
                    "openapi-operations",
                    "review-notes",
                    "scip-occurrences",
                ],
            ),
            S + "analyzedScope": ([STRING], 1, None, []),
            S + "payloadDigest": ([STRING], 1, 1, []),
            S + "coverageState": ([STRING], 1, 1, ["complete", "failed", "partial"]),
        },
    },
    "ImportIssue": {
        "storage": "SwImportIssue",
        "properties": {
            S + "activityRef": ([PROV + "Activity"], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, 1, []),
            S + "severity": ([STRING], 1, 1, ["error", "warning"]),
            S + "issueCode": ([STRING], 1, 1, []),
            S + "fileRef": ([C1 + "Document"], 0, 1, []),
            S + "issueMessage": ([STRING], 0, 1, []),
        },
    },
    "UnresolvedReference": {
        "storage": "SwUnresolvedReference",
        "properties": {
            S + "activityRef": ([PROV + "Activity"], 1, 1, []),
            S + "snapshotRef": ([S + "SourceSnapshot"], 1, 1, []),
            S + "fileRef": ([C1 + "Document"], 1, 1, []),
            S + "symbolText": ([STRING], 1, 1, []),
            S + "unresolvedReason": (
                [STRING],
                1,
                1,
                ["ambiguous", "external-package", "not-indexed", "parse-error"],
            ),
            S + "startLine": ([INTEGER], 1, 1, []),
            S + "startCharacter": ([INTEGER], 1, 1, []),
            S + "endLine": ([INTEGER], 1, 1, []),
            S + "endCharacter": ([INTEGER], 1, 1, []),
        },
    },
}

# Relationship predicates used by ordinary Assertions; the predicate names the
# evidence basis (M08 D6). None has a record-field role.
RELATIONSHIPS: dict[str, list[str]] = {
    "repositoryOf": [S + "SoftwareProduct"],
    "releaseOf": [S + "SoftwareProduct"],
    "releasedAs": [S + "SourceSnapshot"],
    "implementsCapability": [S + "Capability"],
    "documents": [S + "Capability", S + "CodeSymbol", S + "InterfaceOperation"],
    "describesSnapshot": [S + "SourceSnapshot"],
    "implementsOperation": [S + "InterfaceOperation"],
    "declaredCall": [S + "InterfaceOperation"],
    "staticCall": [S + "CodeSymbol"],
    "interpretedCall": [S + "CodeSymbol"],
    "verifies": [S + "Capability", S + "CodeSymbol", S + "InterfaceOperation"],
    "exercised": [S + "InterfaceOperation"],
    "specifiedIn": [C1 + "Document"],
    "definedAt": [S + "SymbolOccurrence"],
    # M09 (ADR-0018): declared test-development context.
    "executionInstructions": [S + "CodeRepository"],
    "fixtureOf": [S + "TestCase"],
    "discrepancy": [C1 + "DocumentPart"],
    # M10 (ADR-0021): declared support aspects and negative applicability.
    "addressesAspect": [S + "Aspect"],
    "notApplicableTo": [S + "SourceSnapshot"],
}


def _prop(
    name: str, ranges: list[str], minimum: int, maximum: int | None, enum: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "ranges": ranges,
        "min_count": minimum,
        "max_count": maximum,
        "enum": enum,
    }


def build_manifest(core: dict[str, Any]) -> dict[str, Any]:
    template = core["classes"][C1 + "Entity"]["properties"]
    classes: dict[str, Any] = {}
    for name, spec in ENTITY_CLASSES.items():
        properties = dict(template)
        for field, (ranges, minimum, maximum, enum) in spec["extra"].items():
            properties[S + field] = _prop(field, ranges, minimum, maximum, enum)
        classes[S + name] = {
            "storage_name": spec["storage"],
            "kind": "entity",
            "key_strategy": "Random",
            "properties": properties,
        }
    for name, spec in RECORD_CLASSES.items():
        properties = {}
        for predicate, (ranges, minimum, maximum, enum) in spec["properties"].items():
            local = predicate.rsplit("#", 1)[1]
            if predicate == PROV + "wasGeneratedBy":
                local = "wasGeneratedBy"
            properties[predicate] = _prop(local, ranges, minimum, maximum, enum)
        classes[S + name] = {
            "storage_name": spec["storage"],
            "kind": "record",
            "key_strategy": "Random",
            "properties": properties,
        }
    predicates = {
        S + name: _prop(name, ranges, 0, None, []) for name, ranges in RELATIONSHIPS.items()
    }
    predicates[DCT + "source"] = _prop("documentSource", [C1 + "Source"], 0, None, [])
    return {
        "name": "software",
        "version": VERSION,
        "requires_core": core["version"],
        "context": "context.jsonld",
        "shapes": "shapes.ttl",
        "classes": classes,
        "predicates": predicates,
    }


def _range_clause(value: str) -> str:
    if value == "@id":
        return "sh:nodeKind sh:IRI"
    if value == RDFS + "Literal":
        return "sh:nodeKind sh:Literal"
    if value.startswith(XSD) or value.startswith(RDF):
        return f"sh:datatype <{value}>"
    return f"sh:class <{value}>"


def _property_shape(predicate: str, definition: dict[str, Any]) -> str:
    parts = [f"sh:path <{predicate}>"]
    if definition["min_count"]:
        parts.append(f"sh:minCount {definition['min_count']}")
    if definition["max_count"] is not None:
        parts.append(f"sh:maxCount {definition['max_count']}")
    ranges = definition["ranges"]
    if len(ranges) == 1:
        parts.append(_range_clause(ranges[0]))
    else:
        parts.append("sh:or ( " + " ".join(f"[ {_range_clause(item)} ]" for item in ranges) + " )")
    if definition["enum"]:
        values = " ".join(f'"{item}"^^<{STRING}>' for item in definition["enum"])
        parts.append(f"sh:in ( {values} )")
    return "    sh:property [ " + " ; ".join(parts) + " ]"


def build_shapes(manifest: dict[str, Any], core_shapes: str) -> str:
    entity_shape = core_shapes.split(f"<{C1}shape-Entity>", 1)[1].split("\n\n", 1)[0]
    blocks: list[str] = []
    for iri, definition in manifest["classes"].items():
        name = iri.rsplit("#", 1)[1]
        if definition["kind"] == "entity":
            body = entity_shape.replace(f"<{C1}Entity>", f"<{iri}>").rstrip()
            extra = [
                _property_shape(predicate, prop)
                for predicate, prop in definition["properties"].items()
                if predicate.startswith(S)
            ]
            if extra:
                if not body.endswith(" ."):
                    raise SystemExit("unexpected core Entity shape layout")
                body = body[: -len(" .")] + " ;\n" + " ;\n".join(extra) + " ."
            blocks.append(f"<{S}shape-{name}>" + body)
        else:
            lines = [
                _property_shape(predicate, prop)
                for predicate, prop in definition["properties"].items()
            ]
            blocks.append(
                f"<{S}shape-{name}> a sh:NodeShape ;\n"
                f"    sh:targetClass <{iri}> ;\n" + " ;\n".join(lines) + " ."
            )
    return "@prefix sh: <http://www.w3.org/ns/shacl#> .\n\n" + "\n\n".join(blocks) + "\n"


def build_files() -> dict[str, str]:
    core = json.loads((ROOT / "profiles/core/profile.json").read_text(encoding="utf-8"))
    manifest = build_manifest(core)
    shapes = build_shapes(manifest, (ROOT / "profiles/core/shapes.ttl").read_text(encoding="utf-8"))
    context = {"@id": f"urn:c1:context:software:{VERSION}", "@context": {"software": S}}
    return {
        "profile.json": json.dumps(manifest, indent=2) + "\n",
        "context.jsonld": json.dumps(context, indent=2) + "\n",
        "shapes.ttl": shapes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if checked-in files differ")
    args = parser.parse_args()
    files = build_files()
    if args.check:
        stale = [
            str(target / name)
            for target in TARGETS
            for name, content in files.items()
            if not (target / name).is_file()
            or (target / name).read_text(encoding="utf-8") != content
        ]
        if stale:
            print("software profile is stale: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("software profile is current")
        return 0
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (target / name).write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
