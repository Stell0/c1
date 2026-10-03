"""Deterministic producer clients for the M08 software profile (M08 D3–D12).

The planning half is pure: it maps checked-in SCIP JSON, OpenAPI documents,
Markdown documentation, Python sources, and JUnit reports into ordinary C1
records. It never runs indexed code, follows URLs, or trusts file content as
instructions. The loading half applies each producer run through reviewed
ChangeSets with deterministic idempotency keys and writes coverage last.

Three producer principals keep attribution separate: `indexer` (SCIP,
OpenAPI, docs, reference-based calls), `analyzer` (competing name-based calls
and attributed interpretations), and `ci` (test runs).
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "fixtures/software-integration"

C1 = "urn:c1:ns:core#"
S = "urn:c1:ns:software#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PROV = "http://www.w3.org/ns/prov#"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"

TOOL_VERSION = "1.0.0"
BATCH_LIMIT = 200
STDLIB_PACKAGE = "python-stdlib"
ROLE_BITS = (
    (0x1, "definition"),
    (0x2, "import"),
    (0x4, "write-access"),
    (0x8, "read-access"),
    (0x10, "generated"),
    (0x20, "test"),
    (0x40, "forward-definition"),
)

Record = dict[str, Any]


# --- identity and literal helpers ---------------------------------------------------


def ident(key: str, kind: str) -> str:
    """Fixture IDs are stable: UUIDv5 bytes over a fixture key, with v4 syntax bits."""
    named = uuid.uuid5(uuid.NAMESPACE_URL, "c1-m08/" + key)
    return f"urn:c1:instance:dev:{kind}/{uuid.UUID(bytes=named.bytes, version=4)}"


def lit(value: str, datatype: str = "string") -> dict[str, str]:
    return {"lexical": value, "datatype": XSD + datatype}


def integer(value: int) -> dict[str, str]:
    return lit(str(value), "integer")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


# --- SCIP v0.10.0 subset ------------------------------------------------------------


@dataclass(frozen=True)
class ScipSymbol:
    scheme: str
    manager: str
    package: str
    version: str
    descriptors: str

    @property
    def kind(self) -> str | None:
        """Only functions/methods and types become CodeSymbols in this subset."""
        if self.descriptors.endswith("()."):
            return "function"
        if self.descriptors.endswith("#"):
            return "type"
        return None

    @property
    def display(self) -> str:
        text = self.descriptors.replace("`", "")
        for suffix in ("().", "#", "."):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break
        return text.replace("/", ".").replace("#", ".")


def _read_field(text: str, position: int) -> tuple[str, int]:
    """Read one space-terminated SCIP field; a double space is a literal space."""
    value: list[str] = []
    while position < len(text):
        char = text[position]
        if char == " ":
            if position + 1 < len(text) and text[position + 1] == " ":
                value.append(" ")
                position += 2
                continue
            return "".join(value), position + 1
        value.append(char)
        position += 1
    raise ValueError("truncated SCIP symbol")


def parse_symbol(text: str) -> ScipSymbol | None:
    """Parse `<scheme> <manager> <package> <version> <descriptors>`; local symbols are None."""
    if text.startswith("local "):
        return None
    position = 0
    fields: list[str] = []
    for _ in range(4):
        value, position = _read_field(text, position)
        fields.append(value)
    descriptors = text[position:]
    if not fields[0] or not descriptors:
        raise ValueError("invalid SCIP symbol")
    scheme, manager, package, version = fields
    return ScipSymbol(scheme, manager, package, version, descriptors)


def occurrence_range(occurrence: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return half-open zero-based (start_line, start_char, end_line, end_char).

    SCIP v0.10.0 typed ranges win when present; older producers such as
    scip-python 0.6.6 emit the packed `range` form of three or four integers.
    """
    typed = occurrence.get("TypedRange")
    if isinstance(typed, dict):
        single = typed.get("SingleLineRange") or typed.get("single_line_range")
        multi = typed.get("MultiLineRange") or typed.get("multi_line_range")
        if isinstance(single, dict):
            line = int(single.get("line", 0))
            return (
                line,
                int(single.get("start_character", 0)),
                line,
                int(single.get("end_character", 0)),
            )
        if isinstance(multi, dict):
            return (
                int(multi.get("start_line", 0)),
                int(multi.get("start_character", 0)),
                int(multi.get("end_line", 0)),
                int(multi.get("end_character", 0)),
            )
    packed = occurrence.get("range")
    if isinstance(packed, list) and len(packed) == 3:
        return int(packed[0]), int(packed[1]), int(packed[0]), int(packed[2])
    if isinstance(packed, list) and len(packed) == 4:
        return int(packed[0]), int(packed[1]), int(packed[2]), int(packed[3])
    raise ValueError("SCIP occurrence has no supported range")


def roles(bits: int) -> list[str]:
    values = [name for mask, name in ROLE_BITS if bits & mask]
    return values or ["reference"]


def position_encoding(document: dict[str, Any]) -> str:
    value = document.get("position_encoding")
    return (
        {1: "utf-8", 2: "utf-16", 3: "utf-32"}.get(value, "unspecified")
        if isinstance(value, int)
        else "unspecified"
    )


# --- source segmentation ------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    kind: str
    text: str
    start_line: int
    end_line: int  # inclusive


def order_key(rank: int) -> str:
    # M06 order keys must not end with "0".
    return f"{rank:05d}u"


def python_parts(text: str, units: list[tuple[int, int]]) -> list[Part]:
    """Split a module into complete top-level units and the text between them.

    Units are whole-line spans taken from SCIP definition enclosing ranges.
    Whitespace-only gaps are not stored as parts.
    """
    lines = text.splitlines(keepends=True)
    parts: list[Part] = []
    cursor = 0
    for start, end in sorted(units):
        if start < cursor:
            continue
        if start > cursor:
            gap = "".join(lines[cursor:start])
            if gap.strip():
                parts.append(Part("code:python", gap, cursor, start - 1))
        parts.append(Part("code-unit:python", "".join(lines[start : end + 1]), start, end))
        cursor = end + 1
    if cursor < len(lines):
        gap = "".join(lines[cursor:])
        if gap.strip():
            parts.append(Part("code:python", gap, cursor, len(lines) - 1))
    return parts


def markdown_parts(text: str) -> list[Part]:
    """A heading line starts a new section; each section keeps its exact body text."""
    lines = text.splitlines(keepends=True)
    parts: list[Part] = []
    body: list[str] = []
    body_start = 0
    fenced = False

    def flush(end: int) -> None:
        if body and "".join(body).strip():
            parts.append(Part("text", "".join(body), body_start, end))

    for number, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if 1 <= level <= 6 and line[level : level + 1] == " ":
                flush(number - 1)
                parts.append(Part(f"heading-{level}", line, number, number))
                body, body_start = [], number + 1
                continue
        body.append(line)
    flush(len(lines) - 1)
    return parts


def section_parts(parts: list[tuple[str, Part]]) -> dict[str, list[str]]:
    """Heading-2 section name -> its heading and body part IDs, in order."""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for identifier, part in parts:
        if part.kind.startswith("heading-"):
            level = int(part.kind.split("-", 1)[1])
            current = part.text.lstrip("#").strip() if level == 2 else None
            if level <= 1:
                continue
        if current is not None:
            result.setdefault(current, []).append(identifier)
    return result


def part_containing(parts: list[tuple[str, Part]], line: int) -> str | None:
    for identifier, part in parts:
        if part.start_line <= line <= part.end_line:
            return identifier
    return None


# --- planning -----------------------------------------------------------------------


@dataclass
class Inputs:
    fixture: dict[str, Any]
    files: dict[str, dict[str, bytes]]  # snapshot -> path -> bytes
    scip: dict[str, dict[str, Any]]
    reports: dict[str, bytes]
    guides: dict[str, bytes] = field(default_factory=dict)


def load_inputs(root: Path = FIXTURE) -> Inputs:
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    files: dict[str, dict[str, bytes]] = {}
    scip: dict[str, dict[str, Any]] = {}
    for key, snapshot in fixture["snapshots"].items():
        tree = root / "repos" / snapshot["repository"] / key
        files[key] = {
            path.relative_to(tree).as_posix(): path.read_bytes()
            for path in sorted(tree.rglob("*"))
            if path.is_file()
        }
        scip[key] = json.loads((root / "scip" / f"{key}.json").read_text(encoding="utf-8"))
    reports = {run["report"]: (root / run["report"]).read_bytes() for run in fixture["test_runs"]}
    guides = {path: (root / path).read_bytes() for path in fixture.get("guides", {})}
    return Inputs(fixture, files, scip, reports, guides)


@dataclass
class Run:
    """One producer run: records in dependency order, then coverage per scope."""

    key: str
    actor: str
    method: str
    snapshot: str
    activity: Record
    records: list[Record] = field(default_factory=list)
    coverage: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, record: Record) -> str:
        self.records.append(record)
        return str(record["id"])

    def touch(self, scope: str, path: str, *, failed: bool = False) -> None:
        entry = self.coverage.setdefault(scope, {"paths": set(), "failed": False})
        entry["paths"].add(path)
        entry["failed"] = entry["failed"] or failed

    def payload_digest(self) -> str:
        return canonical_digest(
            {"method": self.method, "snapshot": self.snapshot, "records": self.records}
        )

    def scope_digest(self, scope: str) -> str:
        """Digest only the records bound to one scope.

        A coverage record is readable by that scope's audience; a digest over
        the whole run would let it observe records in other, hidden scopes.
        """
        return canonical_digest(
            {
                "method": self.method,
                "snapshot": self.snapshot,
                "scope": scope,
                "records": [record for record in self.records if record["scope"] == scope],
            }
        )

    def coverage_records(self) -> list[Record]:
        values = []
        for scope in sorted(self.coverage):
            entry = self.coverage[scope]
            digest = self.scope_digest(scope)
            values.append(
                {
                    "id": coverage_id(self.method, self.actor, self.snapshot, scope, digest),
                    "types": [S + "ImportCoverage"],
                    "scope": scope,
                    "properties": {
                        S + "activityRef": [self.activity["id"]],
                        S + "snapshotRef": [snapshot_id(self.snapshot)],
                        S + "importMethod": [lit(self.method)],
                        S + "analyzedScope": [lit(path) for path in sorted(entry["paths"])],
                        S + "payloadDigest": [lit(digest)],
                        S + "coverageState": [lit("partial" if entry["failed"] else "complete")],
                    },
                }
            )
        return values


def coverage_id(method: str, actor: str, snapshot: str, scope: str, digest: str) -> str:
    return ident(f"coverage/{method}/{actor}/{snapshot}/{scope}/{digest}", "coverage")


def snapshot_id(key: str) -> str:
    return ident(f"snapshot/{key}", "entity")


def source_id(key: str) -> str:
    return ident(f"source/{key}", "source")


def file_id(snapshot: str, path: str) -> str:
    return ident(f"file/{snapshot}/{path}", "document")


def part_id(snapshot: str, path: str, index: int) -> str:
    return ident(f"part/{snapshot}/{path}/{index}", "part")


def symbol_id(repository: str, descriptors: str) -> str:
    return ident(f"symbol/{repository}/{descriptors}", "entity")


def product_id(key: str) -> str:
    return ident(f"product/{key}", "entity")


def repository_id(key: str) -> str:
    return ident(f"repository/{key}", "entity")


def operation_id(provider: str, operation: str) -> str:
    return ident(f"operation/{provider}/{operation}", "entity")


def capability_id(key: str) -> str:
    return ident(f"capability/{key}", "entity")


def test_case_id(key: str) -> str:
    return ident(f"test-case/{key}", "entity")


def aspect_id(key: str) -> str:
    return ident(f"aspect/{key}", "entity")


def guide_id(path: str) -> str:
    return ident(f"guide/{path}", "document")


def guide_part_id(path: str, index: int) -> str:
    return ident(f"guide-part/{path}/{index}", "part")


def configuration_id(key: str) -> str:
    return ident(f"configuration/{key}", "configuration")


def entity(identifier: str, cls: str, label: str, scope: str, **fields: Any) -> Record:
    properties: dict[str, list[Any]] = {
        SKOS + "prefLabel": [lit(label)],
        C1 + "lifecycle": [lit("active")],
    }
    properties.update(fields)
    return {"id": identifier, "types": [S + cls], "scope": scope, "properties": properties}


def assertion(
    key: str,
    subject: str,
    predicate: str,
    obj: str,
    *,
    scope: str,
    principal: str,
    activity: str,
    evidence: str,
    origin: str = "imported",
) -> Record:
    return {
        "id": ident(f"assertion/{key}", "assertion"),
        "types": [C1 + "Assertion"],
        "scope": scope,
        "properties": {
            RDF + "subject": [subject],
            RDF + "predicate": [predicate],
            RDF + "object": [obj],
            C1 + "origin": [lit(origin)],
            C1 + "reviewState": [lit("reported")],
            C1 + "lifecycle": [lit("active")],
            C1 + "manualStatement": [lit("false", "boolean")],
            PROV + "wasAttributedTo": [principal],
            PROV + "wasGeneratedBy": [activity],
            C1 + "evidence": [evidence],
        },
    }


def evidence_record(
    key: str,
    claim: str,
    target: str,
    revision: str,
    *,
    scope: str,
    activity: str,
    selector: str | None = None,
) -> Record:
    properties: dict[str, list[Any]] = {
        C1 + "assertionRef": [claim],
        OA + "hasSource": [target],
        C1 + "sourceRevision": [lit(revision)],
        PROV + "wasGeneratedBy": [activity],
    }
    if selector:
        properties[OA + "hasSelector"] = [selector]
    return {
        "id": ident(f"evidence/{key}", "evidence"),
        "types": [C1 + "Evidence"],
        "scope": scope,
        "properties": properties,
    }


def claim_with_evidence(
    run: Run,
    key: str,
    subject: str,
    predicate: str,
    obj: str,
    *,
    scope: str,
    principal: str,
    target: str,
    revision: str,
    selector: Record | None = None,
    origin: str = "imported",
) -> str:
    claim = ident(f"assertion/{key}", "assertion")
    selector_id = None
    if selector is not None:
        selector_id = run.add({**selector, "scope": scope})
    evidence = evidence_record(
        key,
        claim,
        target,
        revision,
        scope=scope,
        activity=run.activity["id"],
        selector=selector_id,
    )
    run.add(
        assertion(
            key,
            subject,
            predicate,
            obj,
            scope=scope,
            principal=principal,
            activity=run.activity["id"],
            evidence=evidence["id"],
            origin=origin,
        )
    )
    run.add(evidence)
    return claim


def position_selector(key: str, start: int, end: int) -> Record:
    return {
        "id": ident(f"selector/{key}", "selector"),
        "types": [C1 + "Selector"],
        "properties": {
            C1 + "selectorKind": [lit("TextPositionSelector")],
            OA + "start": [integer(start)],
            OA + "end": [integer(end)],
        },
    }


def quote_selector(key: str, exact: str) -> Record:
    return {
        "id": ident(f"selector/{key}", "selector"),
        "types": [C1 + "Selector"],
        "properties": {
            C1 + "selectorKind": [lit("TextQuoteSelector")],
            OA + "exact": [lit(exact)],
        },
    }


def restrictive(scope: str, *others: str) -> str:
    return "sw-restricted" if "sw-restricted" in (scope, *others) else scope


def activity_record(key: str, principal: str, method: str, used: list[str], scope: str) -> Record:
    return {
        "id": ident(f"activity/{key}", "activity"),
        "types": [PROV + "Activity"],
        "scope": scope,
        "properties": {
            PROV + "wasAttributedTo": [principal],
            PROV + "used": used,
            C1 + "toolName": [lit("c1-software-producer")],
            C1 + "toolVersion": [lit(TOOL_VERSION)],
            C1 + "method": [lit(method)],
            C1 + "outcome": [lit("imported")],
        },
    }


class Planner:
    """Derive every producer run from the checked-in inputs."""

    def __init__(self, inputs: Inputs, principals: dict[str, str]) -> None:
        self.inputs = inputs
        self.fixture = inputs.fixture
        self.principals = principals
        self._symbol_scope: dict[tuple[str, str], str] = {}
        self._parts: dict[tuple[str, str], list[tuple[str, Part]]] = {}
        # Published guides: path -> (document revision, stored parts).
        self._guide_parts: dict[str, tuple[str, list[tuple[str, Part]]]] = {}
        self._created_symbols: set[str] = set()
        self._parsed: dict[str, dict[str, bool]] = {}
        self._occurrences: dict[str, dict[tuple[str, int, int, str], str]] = {}

    # helpers ---------------------------------------------------------------------------

    def repo_of(self, snapshot: str) -> str:
        return str(self.fixture["snapshots"][snapshot]["repository"])

    def commit(self, snapshot: str) -> str:
        return str(self.fixture["snapshots"][snapshot]["commit"])

    def file_scope(self, snapshot: str, path: str) -> str:
        repository = self.fixture["repositories"][self.repo_of(snapshot)]
        return str(self.fixture["path_scopes"].get(path, repository["scope"]))

    def parsed(self, snapshot: str, path: str) -> bool:
        cache = self._parsed.setdefault(snapshot, {})
        if path not in cache:
            try:
                ast.parse(self.inputs.files[snapshot][path].decode("utf-8"), filename=path)
                cache[path] = True
            except (SyntaxError, UnicodeDecodeError):
                cache[path] = False
        return cache[path]

    def definitions(self, snapshot: str) -> dict[str, list[tuple[int, int]]]:
        """Top-level definition line spans per parsed Python file."""
        result: dict[str, list[tuple[int, int]]] = {}
        for document in self.inputs.scip[snapshot]["documents"]:
            path = document["relative_path"]
            if not path.endswith(".py") or not self.parsed(snapshot, path):
                continue
            spans: list[tuple[int, int]] = []
            for occurrence in document.get("occurrences", []):
                symbol = parse_symbol(occurrence["symbol"])
                enclosing = occurrence.get("enclosing_range")
                if (
                    symbol is None
                    or symbol.kind is None
                    or not occurrence.get("symbol_roles", 0) & 0x1
                    or not isinstance(enclosing, list)
                ):
                    continue
                start, end = (
                    int(enclosing[0]),
                    int(enclosing[2] if len(enclosing) == 4 else enclosing[0]),
                )
                if enclosing[1] == 0:
                    spans.append((start, end))
            # Keep only outermost units (methods stay inside their class unit).
            outer = [
                span
                for span in spans
                if not any(o != span and o[0] <= span[0] and span[1] <= o[1] for o in spans)
            ]
            result[path] = sorted(set(outer))
        return result

    # seed ------------------------------------------------------------------------------

    def seed(self) -> Run:
        principal = self.principals["indexer"]
        run = Run(
            "seed",
            "indexer",
            "docs",
            "a1",
            activity_record("seed", principal, "docs", [], "sw-shared"),
        )
        run.add(run.activity)
        for key, product in self.fixture["products"].items():
            run.add(entity(product_id(key), "SoftwareProduct", product["label"], product["scope"]))
        capability = self.fixture["capability"]
        run.add(
            entity(
                capability_id(capability["key"]),
                "Capability",
                capability["label"],
                capability["scope"],
            )
        )
        for key, parameters in self.fixture["configurations"].items():
            run.add(
                {
                    "id": configuration_id(key),
                    "types": [S + "Configuration"],
                    "scope": "sw-shared",
                    "properties": {
                        S + "configurationName": [lit(key)],
                        S + "parameter": [lit(item) for item in sorted(parameters)],
                        S + "configurationDigest": [lit(canonical_digest(sorted(parameters)))],
                    },
                }
            )
        for key, repository in self.fixture["repositories"].items():
            run.add(
                entity(
                    repository_id(key),
                    "CodeRepository",
                    key,
                    repository["scope"],
                    **{S + "repositoryKey": [lit(key)]},
                )
            )
        for key, test in self.fixture["test_cases"].items():
            scope = self.fixture["repositories"][test["repository"]]["scope"]
            run.add(entity(test_case_id(key), "TestCase", key, scope))
        for key, label in sorted(self.fixture.get("aspects", {}).items()):
            run.add(
                entity(
                    aspect_id(key),
                    "Aspect",
                    label,
                    "sw-shared",
                )
            )
        run.coverage = {}
        return run

    # scip-occurrences ------------------------------------------------------------------

    def snapshot_run(self, snapshot: str) -> Run:
        """Snapshot, release, source, files and parts, symbols, occurrences, issues."""
        repo = self.repo_of(snapshot)
        repository = self.fixture["repositories"][repo]
        repo_scope = repository["scope"]
        principal = self.principals["indexer"]
        commit = self.commit(snapshot)
        meta = self.fixture["snapshots"][snapshot]
        run = Run(
            f"scip/{snapshot}",
            "indexer",
            "scip-occurrences",
            snapshot,
            activity_record(
                f"scip/{snapshot}", principal, "scip-occurrences", [source_id(snapshot)], repo_scope
            ),
        )
        run.add(
            {
                "id": source_id(snapshot),
                "types": [C1 + "Source"],
                "scope": repo_scope,
                "properties": {
                    DCT + "title": [lit(f"{repo} {snapshot} source tree")],
                    C1 + "sourceKind": [lit("git-snapshot")],
                    DCT + "identifier": [lit(f"git:{repo}@{commit}")],
                    C1 + "sourceRevision": [lit(commit)],
                },
            }
        )
        run.add(run.activity)
        run.add(
            entity(
                snapshot_id(snapshot),
                "SourceSnapshot",
                f"{repo} {snapshot}",
                repo_scope,
                **{
                    S + "repositoryRef": [repository_id(repo)],
                    S + "commitId": [lit(commit)],
                    S + "treeId": [lit(meta["tree"])],
                },
            )
        )
        release = ident(f"release/{snapshot}", "entity")
        product = product_id(repository["product"])
        run.add(
            entity(
                release,
                "SoftwareRelease",
                f"{self.fixture['products'][repository['product']]['label']} {meta['release']}",
                repo_scope,
                **{S + "releaseVersion": [lit(meta["release"])]},
            )
        )
        for predicate, subject, obj in (
            ("releaseOf", release, product),
            ("releasedAs", release, snapshot_id(snapshot)),
        ):
            claim_with_evidence(
                run,
                f"{predicate}/{snapshot}",
                subject,
                S + predicate,
                obj,
                scope=repo_scope,
                principal=principal,
                target=source_id(snapshot),
                revision=commit,
            )
        if snapshot == repository["snapshots"][0]:
            claim_with_evidence(
                run,
                f"repositoryOf/{repo}",
                repository_id(repo),
                S + "repositoryOf",
                product,
                scope=repo_scope,
                principal=principal,
                target=source_id(snapshot),
                revision=commit,
            )
        for observation in self.fixture["branch_observations"]:
            if observation["snapshot"] != snapshot:
                continue
            run.add(
                {
                    "id": ident(
                        f"branch/{repo}/{observation['branch']}/{observation['observed_at']}",
                        "branch-observation",
                    ),
                    "types": [S + "BranchObservation"],
                    "scope": repo_scope,
                    "properties": {
                        S + "repositoryRef": [repository_id(repo)],
                        S + "branchName": [lit(observation["branch"])],
                        S + "snapshotRef": [snapshot_id(snapshot)],
                        S + "branchObservedAt": [lit(observation["observed_at"], "dateTimeStamp")],
                    },
                }
            )

        definitions = self.definitions(snapshot)
        for path, data in self.inputs.files[snapshot].items():
            text = data.decode("utf-8")
            scope = self.file_scope(snapshot, path)
            document = file_id(snapshot, path)
            run.add(
                {
                    "id": document,
                    "types": [C1 + "Document"],
                    "scope": scope,
                    "properties": {
                        DCT + "title": [lit(path)],
                        C1 + "sourceRevision": [lit(commit)],
                        C1 + "contentDigest": [lit("sha256:" + sha256(data))],
                    },
                }
            )
            if path.endswith(".py"):
                parts = (
                    python_parts(text, definitions.get(path, []))
                    if self.parsed(snapshot, path)
                    else [Part("code:python", text, 0, len(text.splitlines()) - 1)]
                )
            elif path.endswith(".md"):
                parts = markdown_parts(text)
            elif path.endswith(".json"):
                parts = [Part("code-unit:json", text, 0, len(text.splitlines()) - 1)]
            else:
                parts = [Part("text", text, 0, len(text.splitlines()) - 1)]
            stored: list[tuple[str, Part]] = []
            for index, part in enumerate(parts):
                identifier = part_id(snapshot, path, index)
                run.add(
                    {
                        "id": identifier,
                        "types": [C1 + "DocumentPart"],
                        "scope": scope,
                        "properties": {
                            C1 + "partOfDocument": [document],
                            C1 + "orderKey": [lit(order_key(index + 1))],
                            C1 + "text": [lit(part.text)],
                            C1 + "partKind": [lit(part.kind)],
                        },
                    }
                )
                stored.append((identifier, part))
            self._parts[(snapshot, path)] = stored
            claim_with_evidence(
                run,
                f"source/{snapshot}/{path}",
                document,
                DCT + "source",
                source_id(snapshot),
                scope=scope,
                principal=principal,
                target=source_id(snapshot),
                revision=commit,
            )
            if path.endswith(".py"):
                failed = not self.parsed(snapshot, path)
                run.touch(scope, path, failed=failed)
                if failed:
                    run.add(
                        {
                            "id": ident(f"issue/{snapshot}/{path}", "issue"),
                            "types": [S + "ImportIssue"],
                            "scope": scope,
                            "properties": {
                                S + "activityRef": [run.activity["id"]],
                                S + "snapshotRef": [snapshot_id(snapshot)],
                                S + "severity": [lit("error")],
                                S + "issueCode": [lit("C1-SW-PARSE-001")],
                                S + "fileRef": [document],
                                S + "issueMessage": [
                                    lit(
                                        "The Python parser rejected this file; its index "
                                        "entries were not used."
                                    )
                                ],
                            },
                        }
                    )

        self._symbols_and_occurrences(run, snapshot, repo, principal)
        return run

    def _symbols_and_occurrences(self, run: Run, snapshot: str, repo: str, principal: str) -> None:
        package = self.fixture["repositories"][repo]["package"]
        index = self.inputs.scip[snapshot]
        defined: set[str] = set()
        documents = [
            document
            for document in index["documents"]
            if document["relative_path"].endswith(".py")
            and self.parsed(snapshot, document["relative_path"])
        ]
        for document in documents:
            for occurrence in document.get("occurrences", []):
                symbol = parse_symbol(occurrence["symbol"])
                if (
                    symbol is not None
                    and symbol.package == package
                    and symbol.kind is not None
                    and occurrence.get("symbol_roles", 0) & 0x1
                ):
                    defined.add(symbol.descriptors)
                    key = (repo, symbol.descriptors)
                    if key not in self._symbol_scope:
                        self._symbol_scope[key] = self.file_scope(
                            snapshot, document["relative_path"]
                        )
        for descriptors in sorted(defined):
            identifier = symbol_id(repo, descriptors)
            if identifier in self._created_symbols:
                continue
            self._created_symbols.add(identifier)
            symbol = ScipSymbol("scip-python", "python", package, "", descriptors)
            run.add(
                entity(
                    identifier,
                    "CodeSymbol",
                    symbol.display,
                    self._symbol_scope[(repo, descriptors)],
                    **{
                        S + "repositoryRef": [repository_id(repo)],
                        S + "scipScheme": [lit("scip-python")],
                        S + "packageManager": [lit("python")],
                        S + "packageName": [lit(package)],
                        S + "descriptors": [lit(descriptors)],
                    },
                )
            )
        occurrences = self._occurrences.setdefault(snapshot, {})
        for document in documents:
            path = document["relative_path"]
            scope = self.file_scope(snapshot, path)
            encoding = position_encoding(document)
            parts = self._parts[(snapshot, path)]
            for occurrence in document.get("occurrences", []):
                symbol = parse_symbol(occurrence["symbol"])
                if symbol is None or symbol.kind is None:
                    continue
                sl, sc, el, ec = occurrence_range(occurrence)
                if symbol.package != package:
                    if symbol.package == STDLIB_PACKAGE:
                        continue
                    reason = "external-package"
                elif symbol.descriptors not in defined:
                    reason = "not-indexed"
                else:
                    reason = ""
                if reason:
                    run.add(
                        {
                            "id": ident(
                                f"unresolved/{snapshot}/{path}/{sl}:{sc}/{occurrence['symbol']}",
                                "unresolved",
                            ),
                            "types": [S + "UnresolvedReference"],
                            "scope": scope,
                            "properties": {
                                S + "activityRef": [run.activity["id"]],
                                S + "snapshotRef": [snapshot_id(snapshot)],
                                S + "fileRef": [file_id(snapshot, path)],
                                S + "symbolText": [lit(symbol.display)],
                                S + "unresolvedReason": [lit(reason)],
                                S + "startLine": [integer(sl)],
                                S + "startCharacter": [integer(sc)],
                                S + "endLine": [integer(el)],
                                S + "endCharacter": [integer(ec)],
                            },
                        }
                    )
                    continue
                role_names = roles(int(occurrence.get("symbol_roles", 0)))
                identifier = ident(
                    f"occurrence/{snapshot}/{path}/{sl}:{sc}:{el}:{ec}/{symbol.descriptors}/"
                    + ",".join(role_names),
                    "occurrence",
                )
                properties: dict[str, list[Any]] = {
                    S + "symbolRef": [symbol_id(repo, symbol.descriptors)],
                    S + "snapshotRef": [snapshot_id(snapshot)],
                    S + "fileRef": [file_id(snapshot, path)],
                    S + "role": [lit(item) for item in role_names],
                    S + "startLine": [integer(sl)],
                    S + "startCharacter": [integer(sc)],
                    S + "endLine": [integer(el)],
                    S + "endCharacter": [integer(ec)],
                    S + "positionEncoding": [lit(encoding)],
                    PROV + "wasGeneratedBy": [run.activity["id"]],
                }
                containing = part_containing(parts, sl)
                if containing:
                    properties[S + "partRef"] = [containing]
                occurrence_scope = restrictive(
                    scope, self._symbol_scope[(repo, symbol.descriptors)]
                )
                run.add(
                    {
                        "id": identifier,
                        "types": [S + "SymbolOccurrence"],
                        "scope": occurrence_scope,
                        "properties": properties,
                    }
                )
                occurrences[(path, sl, sc, symbol.descriptors)] = identifier
                test = next(
                    (
                        key
                        for key, value in self.fixture["test_cases"].items()
                        if value["repository"] == repo and value["descriptor"] == symbol.descriptors
                    ),
                    None,
                )
                if test and "definition" in role_names and containing:
                    claim_with_evidence(
                        run,
                        f"definedAt/{test}/{snapshot}",
                        test_case_id(test),
                        S + "definedAt",
                        identifier,
                        scope=scope,
                        principal=principal,
                        target=containing,
                        revision=self.commit(snapshot),
                    )

    # openapi-operations ----------------------------------------------------------------

    def contract_run(self, snapshot: str) -> Run:
        contract = self.fixture["contracts"]
        repo = self.repo_of(snapshot)
        principal = self.principals["indexer"]
        commit = self.commit(snapshot)
        path = contract["path"]
        run = Run(
            f"openapi/{snapshot}",
            "indexer",
            "openapi-operations",
            snapshot,
            activity_record(
                f"openapi/{snapshot}",
                principal,
                "openapi-operations",
                [file_id(snapshot, path)],
                "sw-shared",
            ),
        )
        run.add(run.activity)
        spec = json.loads(self.inputs.files[snapshot][path])
        contract_part = self._parts[(snapshot, path)][0][0]
        run.touch(self.file_scope(snapshot, path), path)
        for template, methods in sorted(spec.get("paths", {}).items()):
            for method, operation in sorted(methods.items()):
                name = operation.get("operationId")
                if not isinstance(name, str) or not name:
                    run.add(
                        {
                            "id": ident(f"issue/{snapshot}/{path}/{method}/{template}", "issue"),
                            "types": [S + "ImportIssue"],
                            "scope": self.file_scope(snapshot, path),
                            "properties": {
                                S + "activityRef": [run.activity["id"]],
                                S + "snapshotRef": [snapshot_id(snapshot)],
                                S + "severity": [lit("warning")],
                                S + "issueCode": [lit("C1-SW-OPENAPI-001")],
                                S + "fileRef": [file_id(snapshot, path)],
                            },
                        }
                    )
                    continue
                operation_identifier = operation_id(contract["provider"], name)
                if snapshot == self.fixture["repositories"][repo]["snapshots"][0]:
                    run.add(
                        entity(
                            operation_identifier,
                            "InterfaceOperation",
                            name,
                            "sw-shared",
                            **{
                                S + "providerRef": [product_id(contract["provider"])],
                                S + "operationId": [lit(name)],
                                S + "httpMethod": [lit(method)],
                                S + "pathTemplate": [lit(template)],
                            },
                        )
                    )
                claim_with_evidence(
                    run,
                    f"specifiedIn/{snapshot}/{name}",
                    operation_identifier,
                    S + "specifiedIn",
                    file_id(snapshot, path),
                    scope="sw-shared",
                    principal=principal,
                    target=contract_part,
                    revision=commit,
                    selector=quote_selector(
                        f"specifiedIn/{snapshot}/{name}", f'"operationId": "{name}"'
                    ),
                )
                handler = operation.get("x-c1-handler")
                if isinstance(handler, str) and "." in handler:
                    module, function = handler.rsplit(".", 1)
                    descriptors = f"`{module}`/{function}()."
                    identifier = symbol_id(repo, descriptors)
                    if identifier in self._created_symbols:
                        claim_with_evidence(
                            run,
                            f"implementsOperation/{snapshot}/{name}",
                            identifier,
                            S + "implementsOperation",
                            operation_identifier,
                            scope=restrictive("sw-shared", self._symbol_scope[(repo, descriptors)]),
                            principal=principal,
                            target=contract_part,
                            revision=commit,
                            selector=quote_selector(
                                f"implementsOperation/{snapshot}/{name}",
                                f'"x-c1-handler": "{handler}"',
                            ),
                        )
        return run

    # docs ------------------------------------------------------------------------------

    def docs_run(self, snapshot: str) -> Run:
        repo = self.repo_of(snapshot)
        principal = self.principals["indexer"]
        commit = self.commit(snapshot)
        run = Run(
            f"docs/{snapshot}",
            "indexer",
            "docs",
            snapshot,
            activity_record(
                f"docs/{snapshot}", principal, "docs", [source_id(snapshot)], "sw-shared"
            ),
        )
        run.add(run.activity)
        for path, spec in sorted(self.fixture["documentation"].items()):
            if spec["repository"] != repo or path not in self.inputs.files[snapshot]:
                continue
            run.touch(self.file_scope(snapshot, path), path)
            if snapshot not in spec["describes"]:
                continue
            document = file_id(snapshot, path)
            first_part = self._parts[(snapshot, path)][0][0]
            scope = self.file_scope(snapshot, path)
            # A copy at this snapshot describes this snapshot and the listed
            # snapshots of other repositories, never other snapshots of its own.
            described_snapshots = [
                item for item in spec["describes"] if item == snapshot or self.repo_of(item) != repo
            ]
            for described in described_snapshots:
                claim_with_evidence(
                    run,
                    f"describes/{snapshot}/{path}/{described}",
                    document,
                    S + "describesSnapshot",
                    snapshot_id(described),
                    scope=restrictive(scope),
                    principal=principal,
                    target=first_part,
                    revision=commit,
                )
            targets: list[str] = []
            if "capability" in spec["documents"]:
                targets.append(capability_id(spec["documents"]["capability"]))
            for name in spec["documents"].get("operations", []):
                targets.append(operation_id(self.fixture["contracts"]["provider"], name))
            for target in targets:
                claim_with_evidence(
                    run,
                    f"documents/{snapshot}/{path}/{target}",
                    document,
                    S + "documents",
                    target,
                    scope=scope,
                    principal=principal,
                    target=first_part,
                    revision=commit,
                )
            # v1.3 (M11 D9): each part of a declared section documents its operations.
            by_section = section_parts(self._parts[(snapshot, path)])
            documented = self.fixture.get("part_documents", {}).get(path, {})
            for section, names in sorted(documented.items()):
                for part in by_section.get(section, []):
                    for name in names:
                        target = operation_id(self.fixture["contracts"]["provider"], name)
                        claim_with_evidence(
                            run,
                            f"part-documents/{snapshot}/{path}/{part}/{name}",
                            part,
                            S + "documents",
                            target,
                            scope=scope,
                            principal=principal,
                            target=part,
                            revision=commit,
                        )
        return run

    # ast-calls -------------------------------------------------------------------------

    def call_sites(
        self, snapshot: str
    ) -> Iterable[tuple[str, ast.Call, ast.FunctionDef | ast.AsyncFunctionDef]]:
        for path, data in sorted(self.inputs.files[snapshot].items()):
            if not path.endswith(".py") or not self.parsed(snapshot, path):
                continue
            tree = ast.parse(data.decode("utf-8"), filename=path)
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call):
                            yield path, inner, node

    def _call_token(self, call: ast.Call) -> tuple[str, int, int] | None:
        func = call.func
        if isinstance(func, ast.Name) and func.end_col_offset is not None:
            return func.id, func.lineno - 1, func.col_offset
        if isinstance(func, ast.Attribute) and func.end_col_offset is not None:
            return (
                func.attr,
                func.end_lineno - 1 if func.end_lineno else func.lineno - 1,
                func.end_col_offset - len(func.attr),
            )
        return None

    def _selector_for(
        self, owner: str, snapshot: str, path: str, part: str, line: int, start: int, end: int
    ) -> Record:
        stored = dict(self._parts[(snapshot, path)])[part]
        lines = stored.text.splitlines(keepends=True)
        offset = sum(len(item) for item in lines[: line - stored.start_line]) + start
        return position_selector(
            f"call/{owner}/{snapshot}/{path}/{line}:{start}", offset, offset + (end - start)
        )

    def calls_run(self, snapshot: str) -> Run:
        """Reference-based static calls and declared operation calls (indexer)."""
        repo = self.repo_of(snapshot)
        principal = self.principals["indexer"]
        commit = self.commit(snapshot)
        run = Run(
            f"calls/{snapshot}",
            "indexer",
            "ast-calls",
            snapshot,
            activity_record(
                f"calls/{snapshot}", principal, "ast-calls", [source_id(snapshot)], "sw-shared"
            ),
        )
        run.add(run.activity)
        occurrences = self._occurrences.get(snapshot, {})
        for path, call, _function in self.call_sites(snapshot):
            token = self._call_token(call)
            run.touch(self.file_scope(snapshot, path), path)
            if token is None:
                continue
            name, line, column = token
            match = next(
                (
                    (key, value)
                    for key, value in occurrences.items()
                    if key[0] == path and key[1] == line and key[2] == column
                ),
                None,
            )
            if match is None:
                continue
            (_, _, _, descriptors), occurrence = match
            part = part_containing(self._parts[(snapshot, path)], line)
            if part is None:
                continue
            target_scope = self._symbol_scope[(repo, descriptors)]
            claim_with_evidence(
                run,
                f"staticCall/indexer/{snapshot}/{path}/{line}:{column}",
                occurrence,
                S + "staticCall",
                symbol_id(repo, descriptors),
                scope=restrictive(self.file_scope(snapshot, path), target_scope),
                principal=principal,
                target=part,
                revision=commit,
                selector=self._selector_for(
                    "indexer", snapshot, path, part, line, column, column + len(name)
                ),
            )
        # Declared operation calls: @calls_operation("<operationId>") decorators.
        for path, data in sorted(self.inputs.files[snapshot].items()):
            if not path.endswith(".py") or not self.parsed(snapshot, path):
                continue
            for node in ast.parse(data.decode("utf-8")).body:
                if not isinstance(node, ast.FunctionDef):
                    continue
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Name)
                        and decorator.func.id == "calls_operation"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and isinstance(decorator.args[0].value, str)
                    ):
                        module = path[:-3].replace("/", ".")
                        descriptors = f"`{module}`/{node.name}()."
                        operation = decorator.args[0].value
                        part = part_containing(self._parts[(snapshot, path)], node.lineno - 1)
                        if part is None or (repo, descriptors) not in self._symbol_scope:
                            continue
                        claim_with_evidence(
                            run,
                            f"declaredCall/{snapshot}/{path}/{node.name}",
                            symbol_id(repo, descriptors),
                            S + "declaredCall",
                            operation_id(self.fixture["contracts"]["provider"], operation),
                            scope=self.file_scope(snapshot, path),
                            principal=principal,
                            target=part,
                            revision=commit,
                            selector=quote_selector(
                                f"declaredCall/{snapshot}/{path}/{node.name}",
                                f'calls_operation("{operation}")',
                            ),
                        )
        return run

    def analyzer_run(self, snapshot: str) -> Run:
        """Competing name-based calls and attributed interpretations (analyzer)."""
        repo = self.repo_of(snapshot)
        principal = self.principals["analyzer"]
        commit = self.commit(snapshot)
        run = Run(
            f"analyzer/{snapshot}",
            "analyzer",
            "ast-calls",
            snapshot,
            activity_record(
                f"analyzer/{snapshot}", principal, "ast-calls", [source_id(snapshot)], "sw-shared"
            ),
        )
        run.add(run.activity)
        occurrences = self._occurrences.get(snapshot, {})
        candidates = sorted(self._symbol_scope)
        for path, call, _function in self.call_sites(snapshot):
            token = self._call_token(call)
            if token is None or token[0] not in self.fixture["name_match_calls"]:
                continue
            name, line, column = token
            run.touch(self.file_scope(snapshot, path), path)
            match = next(
                (
                    value
                    for key, value in occurrences.items()
                    if key[0] == path and key[1] == line and key[2] == column
                ),
                None,
            )
            part = part_containing(self._parts[(snapshot, path)], line)
            if match is None or part is None:
                continue
            # Name-only resolution: the lexicographically first symbol whose final
            # descriptor is the called name, in any repository. This is a
            # deliberately weaker attributed method than reference resolution.
            chosen = next(
                (
                    (r, d)
                    for r, d in candidates
                    if d.endswith(f"/{name}().") and self._symbol_scope[(r, d)] != "sw-restricted"
                ),
                None,
            )
            if chosen is None:
                continue
            claim_with_evidence(
                run,
                f"staticCall/analyzer/{snapshot}/{path}/{line}:{column}",
                match,
                S + "staticCall",
                symbol_id(*chosen),
                scope=self.file_scope(snapshot, path),
                principal=principal,
                target=part,
                revision=commit,
                selector=self._selector_for(
                    "analyzer", snapshot, path, part, line, column, column + len(name)
                ),
                origin="derived",
            )
        if snapshot == self.fixture["repositories"][repo]["snapshots"][0]:
            capability = self.fixture["capability"]
            for implementer_repo, descriptors in capability["implemented_by"]:
                if implementer_repo != repo:
                    continue
                definition_part = self._definition_part(snapshot, repo, descriptors)
                if definition_part is None:
                    continue
                claim_with_evidence(
                    run,
                    f"implementsCapability/{repo}/{descriptors}",
                    symbol_id(repo, descriptors),
                    S + "implementsCapability",
                    capability_id(capability["key"]),
                    scope=self._symbol_scope[(repo, descriptors)],
                    principal=principal,
                    target=definition_part,
                    revision=commit,
                    origin="derived",
                )
            if repo == "shop":
                target = ("ledger", "`ledger.api`/create_invoice().")
                subject = ("shop", "`shop.client`/submit_order().")
                definition_part = self._definition_part(snapshot, *subject)
                if definition_part is not None and target in self._symbol_scope:
                    claim_with_evidence(
                        run,
                        "interpretedCall/submit_order/create_invoice",
                        symbol_id(*subject),
                        S + "interpretedCall",
                        symbol_id(*target),
                        scope="sw-shop",
                        principal=principal,
                        target=definition_part,
                        revision=commit,
                        origin="derived",
                    )
        return run

    def _definition_part(self, snapshot: str, repo: str, descriptors: str) -> str | None:
        for (path, line, _column, found), _identifier in self._occurrences.get(
            snapshot, {}
        ).items():
            if found == descriptors and path.endswith(".py"):
                part = part_containing(self._parts[(snapshot, path)], line)
                if part is not None:
                    return part
        return None

    # junit-runs ------------------------------------------------------------------------

    def ci_run(self, run_spec: dict[str, Any]) -> Run:
        principal = self.principals["ci"]
        key = run_spec["key"]
        first = run_spec["snapshots"][0]
        test = self.fixture["test_cases"][run_spec["test_case"]]
        scope = self.fixture["repositories"][test["repository"]]["scope"]
        run = Run(
            f"ci/{key}",
            "ci",
            "junit-runs",
            first,
            activity_record(f"ci/{key}", principal, "junit-runs", [], scope),
        )
        run.add(run.activity)
        report_bytes = self.inputs.reports[run_spec["report"]]
        result = junit_result(report_bytes)
        report_doc = ident(f"report/{key}", "document")
        revision = "report:" + sha256(report_bytes)
        run.add(
            {
                "id": report_doc,
                "types": [C1 + "Document"],
                "scope": scope,
                "properties": {
                    DCT + "title": [lit(run_spec["report"])],
                    C1 + "sourceRevision": [lit(revision)],
                    C1 + "contentDigest": [lit("sha256:" + sha256(report_bytes))],
                },
            }
        )
        report_part = ident(f"report-part/{key}", "part")
        run.add(
            {
                "id": report_part,
                "types": [C1 + "DocumentPart"],
                "scope": scope,
                "properties": {
                    C1 + "partOfDocument": [report_doc],
                    C1 + "orderKey": [lit(order_key(1))],
                    C1 + "text": [lit(report_bytes.decode("utf-8"))],
                    C1 + "partKind": [lit("code-unit:xml")],
                },
            }
        )
        test_run = ident(f"test-run/{key}", "test-run")
        properties: dict[str, list[Any]] = {
            S + "testCaseRef": [test_case_id(run_spec["test_case"])],
            S + "snapshotRef": [snapshot_id(item) for item in run_spec["snapshots"]],
            S + "configurationRef": [configuration_id(run_spec["configuration"])],
            S + "result": [lit(result)],
            S + "integrationMode": [lit(run_spec["mode"])],
            S + "startedAt": [lit(run_spec["started_at"], "dateTimeStamp")],
            S + "endedAt": [lit(run_spec["ended_at"], "dateTimeStamp")],
            S + "reportRef": [report_doc],
            PROV + "wasGeneratedBy": [run.activity["id"]],
        }
        if run_spec["mocked"]:
            properties[S + "mockedProductRef"] = [product_id(item) for item in run_spec["mocked"]]
        run.add(
            {"id": test_run, "types": [S + "TestRun"], "scope": scope, "properties": properties}
        )
        run.touch(scope, run_spec["report"])
        for name in run_spec["exercised"]:
            claim_with_evidence(
                run,
                f"exercised/{key}/{name}",
                test_run,
                S + "exercised",
                operation_id(self.fixture["contracts"]["provider"], name),
                scope=scope,
                principal=principal,
                target=report_part,
                revision=revision,
            )
        return run

    def verifies_run(self) -> Run:
        principal = self.principals["ci"]
        run = Run(
            "ci/verifies",
            "ci",
            "junit-runs",
            "a1",
            activity_record("ci/verifies", principal, "junit-runs", [], "sw-shared"),
        )
        run.add(run.activity)
        for key, test in sorted(self.fixture["test_cases"].items()):
            scope = self.fixture["repositories"][test["repository"]]["scope"]
            snapshot = self.fixture["repositories"][test["repository"]]["snapshots"][0]
            part = self._definition_part(snapshot, test["repository"], test["descriptor"])
            if part is None:
                continue
            targets = []
            if "capability" in test["verifies"]:
                targets.append(capability_id(test["verifies"]["capability"]))
            for name in test["verifies"].get("operations", []):
                targets.append(operation_id(self.fixture["contracts"]["provider"], name))
            for target in targets:
                claim_with_evidence(
                    run,
                    f"verifies/{key}/{target}",
                    test_case_id(key),
                    S + "verifies",
                    target,
                    scope=scope,
                    principal=principal,
                    target=part,
                    revision=self.commit(snapshot),
                )
        return run

    # M09 declarations ------------------------------------------------------------------

    def testing_run(self, snapshot: str) -> Run:
        """Declared execution instructions and test fixtures (indexer, M09 D3)."""
        repo = self.repo_of(snapshot)
        principal = self.principals["indexer"]
        commit = self.commit(snapshot)
        run = Run(
            f"testing/{snapshot}",
            "indexer",
            "docs",
            snapshot,
            activity_record(
                f"testing/{snapshot}", principal, "docs", [source_id(snapshot)], "sw-shared"
            ),
        )
        run.add(run.activity)
        for path, spec in sorted(self.fixture["execution_instructions"].items()):
            if spec["repository"] != repo or path not in self.inputs.files[snapshot]:
                continue
            parts = self._parts[(snapshot, path)]
            heading = next(
                index
                for index, (_identifier, part) in enumerate(parts)
                if part.kind.startswith("heading-")
                and part.text.lstrip("#").strip() == spec["heading"]
            )
            section = parts[heading + 1][0]
            scope = self.file_scope(snapshot, path)
            run.touch(scope, path)
            # The declared section is stored text only; C1 and this producer never run it.
            claim_with_evidence(
                run,
                f"executionInstructions/{snapshot}/{path}",
                file_id(snapshot, path),
                S + "executionInstructions",
                repository_id(repo),
                scope=scope,
                principal=principal,
                target=section,
                revision=commit,
            )
        for spec in self.fixture["test_fixtures"]:
            if spec["repository"] != repo or (repo, spec["descriptor"]) not in self._symbol_scope:
                continue
            part = self._definition_part(snapshot, repo, spec["descriptor"])
            if part is None:
                continue
            scope = self._symbol_scope[(repo, spec["descriptor"])]
            run.touch(scope, spec["path"])
            claim_with_evidence(
                run,
                f"fixtureOf/{snapshot}/{spec['descriptor']}",
                symbol_id(repo, spec["descriptor"]),
                S + "fixtureOf",
                test_case_id(spec["test_case"]),
                scope=scope,
                principal=principal,
                target=part,
                revision=commit,
            )
        return run

    def review_run(self) -> Run:
        """Checked-in review notes: recorded discrepancies (analyzer, M09 D9)."""
        principal = self.principals["analyzer"]
        run = Run(
            "reviews",
            "analyzer",
            "review-notes",
            "a1",
            activity_record("reviews", principal, "review-notes", [], "sw-shared"),
        )
        run.add(run.activity)
        for note in self.fixture["discrepancies"]:
            snapshot = note["snapshot"]
            implementation = note["implementation"]
            normative = note["normative"]
            parts = {}
            revisions = {}
            for side in (implementation, normative):
                if side["path"] in self._guide_parts:
                    revisions[side["path"]], stored = self._guide_parts[side["path"]]
                else:
                    revisions[side["path"]] = self.commit(snapshot)
                    stored = self._parts[(snapshot, side["path"])]
                found = [identifier for identifier, part in stored if side["quote"] in part.text]
                if len(found) != 1:
                    raise ValueError(f"review quote must occur in exactly one part: {side['path']}")
                parts[side["path"]] = found[0]
            scope = restrictive(
                *(
                    "sw-shared"
                    if side["path"] in self._guide_parts
                    else self.file_scope(snapshot, side["path"])
                    for side in (implementation, normative)
                )
            )
            key = f"discrepancy/{note['key']}"
            claim = ident(f"assertion/{key}", "assertion")
            evidence_ids = []
            for side in (implementation, normative):
                selector = run.add(
                    {**quote_selector(f"{key}/{side['path']}", side["quote"]), "scope": scope}
                )
                evidence = evidence_record(
                    f"{key}/{side['path']}",
                    claim,
                    parts[side["path"]],
                    revisions[side["path"]],
                    scope=scope,
                    activity=run.activity["id"],
                    selector=selector,
                )
                evidence_ids.append(evidence["id"])
                run.add(evidence)
            record = assertion(
                key,
                parts[implementation["path"]],
                S + "discrepancy",
                parts[normative["path"]],
                scope=scope,
                principal=principal,
                activity=run.activity["id"],
                evidence=evidence_ids[0],
            )
            record["properties"][C1 + "evidence"] = evidence_ids
            run.add(record)
            run.touch(scope, implementation["path"])
            run.touch(scope, normative["path"])
        return run

    # M10 support guides and aspects ------------------------------------------------

    def guides_run(self) -> Run:
        """Published support guides in sw-shared with declared applicability (M10 D10)."""
        principal = self.principals["indexer"]
        run = Run(
            "guides",
            "indexer",
            "docs",
            "a1",
            activity_record("guides", principal, "docs", [], "sw-shared"),
        )
        run.add(run.activity)
        for path, spec in sorted(self.fixture.get("guides", {}).items()):
            data = self.inputs.guides[path]
            text = data.decode("utf-8")
            revision = "guide:" + sha256(data)
            document = guide_id(path)
            parts = markdown_parts(text)
            title = parts[0].text.lstrip("#").strip() if parts else path
            run.add(
                {
                    "id": document,
                    "types": [C1 + "Document"],
                    "scope": "sw-shared",
                    "properties": {
                        DCT + "title": [lit(title)],
                        C1 + "sourceRevision": [lit(revision)],
                        C1 + "contentDigest": [lit("sha256:" + sha256(data))],
                        DCT + "issued": [lit(spec["issued"], "date")],
                    },
                }
            )
            stored: list[tuple[str, Part]] = []
            for index, part in enumerate(parts):
                identifier = guide_part_id(path, index)
                run.add(
                    {
                        "id": identifier,
                        "types": [C1 + "DocumentPart"],
                        "scope": "sw-shared",
                        "properties": {
                            C1 + "partOfDocument": [document],
                            C1 + "orderKey": [lit(order_key(index + 1))],
                            C1 + "text": [lit(part.text)],
                            C1 + "partKind": [lit(part.kind)],
                        },
                    }
                )
                stored.append((identifier, part))
            self._guide_parts[path] = (revision, stored)
            first = stored[0][0]

            def section(name: str, stored: list[tuple[str, Part]] = stored) -> str:
                for index, (_identifier, part) in enumerate(stored):
                    if part.kind.startswith("heading-") and part.text.lstrip("#").strip() == name:
                        return stored[index + 1][0]
                raise ValueError(f"guide section not found: {name}")

            def declare(
                key: str,
                predicate: str,
                obj: str,
                target: str,
                path: str = path,
                document: str = document,
                first: str = first,
                revision: str = revision,
            ) -> None:
                claim_with_evidence(
                    run,
                    f"guide/{path}/{key}",
                    document if not target.startswith("part:") else target[5:],
                    S + predicate,
                    obj,
                    scope="sw-shared",
                    principal=principal,
                    target=first if not target.startswith("part:") else target[5:],
                    revision=revision,
                )

            for snapshot in spec["describes"]:
                declare(f"describes/{snapshot}", "describesSnapshot", snapshot_id(snapshot), "")
            if "capability" in spec["documents"]:
                declare(
                    "documents/capability",
                    "documents",
                    capability_id(spec["documents"]["capability"]),
                    "",
                )
            for name in spec["documents"].get("operations", []):
                declare(
                    f"documents/{name}",
                    "documents",
                    operation_id(self.fixture["contracts"]["provider"], name),
                    "",
                )
            for name, aspects in sorted(spec["sections"].items()):
                for aspect in aspects:
                    section_part = section(name)
                    declare(
                        f"aspect/{name}/{aspect}",
                        "addressesAspect",
                        aspect_id(aspect),
                        "part:" + section_part,
                    )
            for snapshot, name in sorted(spec["not_applicable_to"].items()):
                evidence_part = section(name)
                claim_with_evidence(
                    run,
                    f"guide/{path}/not-applicable/{snapshot}",
                    document,
                    S + "notApplicableTo",
                    snapshot_id(snapshot),
                    scope="sw-shared",
                    principal=principal,
                    target=evidence_part,
                    revision=revision,
                )
        return run

    def aspects_run(self) -> Run:
        """Attributed aspect interpretations on code (analyzer, M10 D2)."""
        principal = self.principals["analyzer"]
        run = Run(
            "aspects",
            "analyzer",
            "review-notes",
            "a1",
            activity_record("aspects", principal, "review-notes", [], "sw-shared"),
        )
        run.add(run.activity)
        for item in self.fixture.get("code_aspects", []):
            repo, snapshot, descriptors = item["repository"], item["snapshot"], item["descriptor"]
            part = self._definition_part(snapshot, repo, descriptors)
            if part is None or (repo, descriptors) not in self._symbol_scope:
                continue
            claim_with_evidence(
                run,
                f"aspect/{repo}/{snapshot}/{descriptors}/{item['aspect']}",
                symbol_id(repo, descriptors),
                S + "addressesAspect",
                aspect_id(item["aspect"]),
                scope=self._symbol_scope[(repo, descriptors)],
                principal=principal,
                target=part,
                revision=self.commit(snapshot),
                origin="derived",
            )
        return run

    def runs(self) -> list[Run]:
        """All runs in dependency order; repeatable (planning state is reset)."""
        self._symbol_scope.clear()
        self._parts.clear()
        self._created_symbols.clear()
        self._occurrences.clear()
        self._guide_parts.clear()
        result = [self.seed()]
        order = ["a1", "b1", "a2", "b2"]
        # Every snapshot exists before contracts and documentation that may
        # describe snapshots of the other repository.
        for key in order:
            result.append(self.snapshot_run(key))
        for key in order:
            if self.repo_of(key) == self.fixture["contracts"]["repository"]:
                result.append(self.contract_run(key))
        for key in order:
            result.append(self.docs_run(key))
        result.append(self.guides_run())
        for key in order:
            result.append(self.calls_run(key))
        # The competing analyzer and the declared test context are exercised on
        # each repository's first snapshot only (a1, b1): later snapshots would
        # repeat the same cases at about 20 s of load time per ChangeSet.
        first = [
            self.fixture["repositories"][name]["snapshots"][0]
            for name in self.fixture["repositories"]
        ]
        for key in order:
            if key in first:
                result.append(self.analyzer_run(key))
        result.append(self.aspects_run())
        if "review_rule" in self.fixture:
            from scripts import doc_review_rule

            spec = self.fixture["review_rule"]
            result.append(doc_review_rule.rule_run(self, spec["target"], spec["checked_at"]))
        for key in order:
            if key in first:
                result.append(self.testing_run(key))
        result.append(self.review_run())
        result.append(self.verifies_run())
        for spec in self.fixture["test_runs"]:
            result.append(self.ci_run(spec))
        # A run that would record nothing but its own activity is not submitted.
        return [run for run in result if run.key == "seed" or len(run.records) > 1]


# --- M09: external consumer results ---------------------------------------------------

CONSUMER_CASE = "consumer-zero-amount"
CONSUMER_PATH = "consumer/test_invoice_zero_amount_rejected.py"


def canonical_junit(report: bytes) -> bytes:
    """Keep only the JUnit subset C1 records: one testcase, its name, and its outcome.

    Timing, host, and timestamp attributes vary per execution; dropping them
    makes an identical outcome an identical, idempotent import.
    """
    result = junit_result(report)
    case = next(ET.fromstring(report).iter("testcase"))

    def attribute(value: str) -> str:
        return escape(value, {'"': "&quot;"})

    classname, name = attribute(case.get("classname", "")), attribute(case.get("name", ""))
    attributes = f'classname="{classname}" name="{name}"'
    body = ""
    if result in {"fail", "error"}:
        tag = "failure" if result == "fail" else "error"
        detail = case.find(tag)
        message = detail.get("message", "") if detail is not None else ""
        body = f'<{tag} message="{attribute(message[:500])}"/>'
    elif result == "skipped":
        body = "<skipped/>"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuite name="consumer" tests="1">'
        f"<testcase {attributes}>{body}</testcase></testsuite>\n"
    ).encode()


def consumer_case_run(principal: str) -> Run:
    """The reviewed external test as a Document and TestCase that verifies createInvoice."""
    data = (FIXTURE / CONSUMER_PATH).read_bytes()
    revision = "consumer:" + sha256(data)
    run = Run(
        "consumer/case",
        "ci",
        "junit-runs",
        "a1",
        activity_record("consumer/case", principal, "junit-runs", [], "sw-ledger"),
    )
    run.add(run.activity)
    document = ident(f"consumer/{CONSUMER_PATH}", "document")
    part = ident(f"consumer-part/{CONSUMER_PATH}", "part")
    run.add(
        {
            "id": document,
            "types": [C1 + "Document"],
            "scope": "sw-ledger",
            "properties": {
                DCT + "title": [lit(CONSUMER_PATH)],
                C1 + "sourceRevision": [lit(revision)],
                C1 + "contentDigest": [lit("sha256:" + sha256(data))],
            },
        }
    )
    run.add(
        {
            "id": part,
            "types": [C1 + "DocumentPart"],
            "scope": "sw-ledger",
            "properties": {
                C1 + "partOfDocument": [document],
                C1 + "orderKey": [lit(order_key(1))],
                C1 + "text": [lit(data.decode("utf-8"))],
                C1 + "partKind": [lit("code:python")],
            },
        }
    )
    run.add(entity(test_case_id(CONSUMER_CASE), "TestCase", CONSUMER_CASE, "sw-ledger"))
    claim_with_evidence(
        run,
        f"verifies/{CONSUMER_CASE}",
        test_case_id(CONSUMER_CASE),
        S + "verifies",
        operation_id("ledger", "createInvoice"),
        scope="sw-ledger",
        principal=principal,
        target=part,
        revision=revision,
        selector=quote_selector(f"verifies/{CONSUMER_CASE}", 'create_invoice("acme", 0)'),
    )
    run.touch("sw-ledger", CONSUMER_PATH)
    return run


def consumer_run(snapshot: str, result: str, report: bytes, principal: str) -> Run:
    """One external execution of the reviewed test at one fixture snapshot."""
    key = f"consumer/{snapshot}"
    run = Run(
        key,
        "ci",
        "junit-runs",
        snapshot,
        activity_record(key, principal, "junit-runs", [], "sw-ledger"),
    )
    run.add(run.activity)
    if junit_result(report) != result:
        raise ValueError("canonical report disagrees with the recorded result")
    revision = "report:" + sha256(report)
    report_doc = ident(f"report/{key}", "document")
    report_part = ident(f"report-part/{key}", "part")
    run.add(
        {
            "id": report_doc,
            "types": [C1 + "Document"],
            "scope": "sw-ledger",
            "properties": {
                DCT + "title": [lit(f"consumer-{snapshot}.xml")],
                C1 + "sourceRevision": [lit(revision)],
                C1 + "contentDigest": [lit("sha256:" + sha256(report))],
            },
        }
    )
    run.add(
        {
            "id": report_part,
            "types": [C1 + "DocumentPart"],
            "scope": "sw-ledger",
            "properties": {
                C1 + "partOfDocument": [report_doc],
                C1 + "orderKey": [lit(order_key(1))],
                C1 + "text": [lit(report.decode("utf-8"))],
                C1 + "partKind": [lit("code-unit:xml")],
            },
        }
    )
    run.add(
        {
            "id": ident(f"test-run/{key}", "test-run"),
            "types": [S + "TestRun"],
            "scope": "sw-ledger",
            "properties": {
                S + "testCaseRef": [test_case_id(CONSUMER_CASE)],
                S + "snapshotRef": [snapshot_id(snapshot)],
                S + "configurationRef": [configuration_id("default")],
                S + "result": [lit(result)],
                S + "integrationMode": [lit("live")],
                S + "reportRef": [report_doc],
                PROV + "wasGeneratedBy": [run.activity["id"]],
            },
        }
    )
    run.touch("sw-ledger", f"consumer-{snapshot}.xml")
    return run


def without_scopes(runs: list[Run], scopes: set[str]) -> list[Run]:
    """The same runs as if records in `scopes` had never been written (T07 twin)."""
    result = []
    for run in runs:
        copy = Run(run.key, run.actor, run.method, run.snapshot, run.activity)
        copy.records = [record for record in run.records if record["scope"] not in scopes]
        copy.coverage = {
            scope: entry for scope, entry in run.coverage.items() if scope not in scopes
        }
        result.append(copy)
    return result


def junit_result(report: bytes) -> str:
    """Bounded JUnit subset: no DTDs or entities; one testcase; pass/fail/error/skipped."""
    if b"<!DOCTYPE" in report or b"<!ENTITY" in report:
        raise ValueError("JUnit report with a DTD is rejected")
    root = ET.fromstring(report)
    cases = list(root.iter("testcase"))
    if len(cases) != 1:
        raise ValueError("JUnit subset expects exactly one testcase per report")
    children = {child.tag for child in cases[0]}
    if "error" in children:
        return "error"
    if "failure" in children:
        return "fail"
    if "skipped" in children:
        return "skipped"
    return "pass"


def batches(run: Run) -> list[list[Record]]:
    records = [*run.records, *run.coverage_records()]
    return [records[start : start + BATCH_LIMIT] for start in range(0, len(records), BATCH_LIMIT)]


def idempotency_key(run: Run, index: int, batch: list[Record], base: str) -> str:
    """An exact retry (same batch, same base) replays; anything else is a new proposal."""
    digest = sha256(
        "|".join(
            (
                run.method,
                run.actor,
                run.key,
                run.snapshot,
                str(index),
                base,
                canonical_digest(batch),
            )
        ).encode()
    )
    return "sw1-" + digest[:60]


# --- loading ------------------------------------------------------------------------


async def install_and_prepare(loader: Any, fixture: dict[str, Any]) -> dict[str, str]:
    """Install the profile, create scopes, and grant producer and reader roles."""
    await loader.grant_instance(await loader.whoami("admin"), "schema_admin")
    await loader.grant_instance(await loader.whoami("reviewer"), "schema_admin")
    catalog = await loader.request("GET", "/v1/catalog", actor="admin")
    if fixture["profile"] not in catalog.get("profile_versions", {}):
        await loader.apply_changeset(
            [{"kind": "install_profile", "profile": fixture["profile"]}],
            author="admin",
            reviewer="reviewer",
            base=(await loader.request("GET", "/v1/instance", actor="admin"))["knowledge_revision"],
        )
    existing = {
        item["id"]
        for item in (await loader.request("GET", "/v1/access-scopes", actor="admin"))[
            "access_scopes"
        ]
    }
    principals = {
        actor: await loader.whoami(actor) for actor in ("indexer", "analyzer", "ci", "reviewer")
    }
    users = sorted(name for name in fixture["readers"] if name != "carol")
    readers = {name: await loader._whoami_user(name) for name in users}
    readers["carol"] = principals["reviewer"]
    settings = fixture.get("scope_settings", {})
    for key, label in fixture["scopes"].items():
        setting = settings.get(key, {})
        # The creator administers the scope and grants every role in it.
        creator = setting.get("creator", "admin")
        if key not in existing:
            body: dict[str, Any] = {"id": key, "label": label}
            if "kind" in setting:
                body["kind"] = setting["kind"]
            await loader.request(
                "POST", "/v1/access-scopes", actor=creator, json_body=body, expected=(201,)
            )
        for actor in setting.get("producers", ("indexer", "analyzer", "ci")):
            for role in ("reader", "creator", "contributor"):
                await loader._membership(key, principals[actor], role, actor=creator)
        for actor in setting.get("service_readers", ()):
            await loader._membership(key, principals[actor], "reader", actor=creator)
        await loader._membership(key, principals["reviewer"], "reader", actor=creator)
        await loader._membership(key, principals["reviewer"], "reviewer", actor=creator)
        for name, allowed in fixture["readers"].items():
            if name in readers and name != "carol" and key in allowed:
                await loader._membership(key, readers[name], "reader", actor=creator)
        for name, role in fixture.get("scope_roles", {}).get(key, []):
            await loader._membership(key, readers[name], role, actor=creator)
    return {
        "indexer": principals["indexer"],
        "analyzer": principals["analyzer"],
        "ci": principals["ci"],
    }


def operations(records: list[Record]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "create",
            "record": {key: record[key] for key in ("id", "types", "properties")},
            "scope_id": record["scope"],
        }
        for record in records
    ]


async def apply_run(loader: Any, run: Run, *, skip_complete: bool = True) -> dict[str, Any]:
    """Apply one run; a readable complete coverage record with this digest is a no-op."""
    if skip_complete and run.coverage:
        first_scope = sorted(run.coverage)[0]
        existing = await loader.client.get(
            "/v1/resources/"
            + quote(
                coverage_id(
                    run.method, run.actor, run.snapshot, first_scope, run.scope_digest(first_scope)
                ),
                safe="",
            ),
            headers={"Authorization": "Bearer " + await loader._actor_token(run.actor)},
        )
        if existing.status_code == 200:
            return {"run": run.key, "state": "skipped", "reason": "complete coverage exists"}
    applied = 0
    token = await loader._actor_token(run.actor)
    for index, batch in enumerate(batches(run)):
        # A ChangeSet commits all of its records or none; if the batch's first
        # record is readable, this batch was already applied by an earlier attempt.
        probe = await loader.client.get(
            "/v1/resources/" + quote(str(batch[0]["id"]), safe=""),
            headers={"Authorization": "Bearer " + token},
        )
        if probe.status_code == 200:
            continue
        base = (await loader.request("GET", "/v1/instance", actor=run.actor))["knowledge_revision"]
        await loader.apply_changeset(
            operations(batch),
            author=run.actor,
            reviewer="reviewer",
            base=base,
            idempotency_key=idempotency_key(run, index, batch, base),
        )
        applied += len(batch)
    return {"run": run.key, "state": "applied", "records": applied}


async def load_software_integration(
    loader: Any,
    *,
    only: set[str] | None = None,
    transform: Callable[[list[Run]], list[Run]] | None = None,
) -> dict[str, Any]:
    """Install, prepare, and apply every producer run in dependency order.

    Each run result records the knowledge revision after it, so a caller can
    query the state before later snapshots were ingested.
    """
    inputs = load_inputs()
    principals = await install_and_prepare(loader, inputs.fixture)
    planner = Planner(inputs, principals)
    runs = planner.runs()
    if transform is not None:
        runs = transform(runs)
    results = []
    for run in runs:
        if only is not None and run.key not in only:
            continue
        outcome = await apply_run(loader, run)
        outcome["revision_after"] = (await loader.request("GET", "/v1/instance", actor="reviewer"))[
            "knowledge_revision"
        ]
        results.append(outcome)
    revision = (await loader.request("GET", "/v1/instance", actor="reviewer"))["knowledge_revision"]
    return {
        "fixture": inputs.fixture["name"],
        "state": "applied",
        "revision": revision,
        "runs": results,
        "principals": principals,
        "planner": planner,
    }


async def _main(database: str | None) -> dict[str, Any]:
    from scripts.load_fixture import Loader, api_client

    async with api_client(database) as client:
        loader = await Loader.connect(client)
        value = await load_software_integration(loader)
        return {key: value[key] for key in ("fixture", "state", "revision")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=["software-integration"], required=True)
    parser.add_argument("--database", help="must match the trusted local knowledge database")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_main(args.database)), sort_keys=True))


if __name__ == "__main__":
    main()
