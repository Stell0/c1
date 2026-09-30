"""M09 D4–D7: deterministic test-development selection over authorized records only."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from c1.context.budget import build_page, prepare_units
from c1.context.markdown import _safe
from c1.context.profiles import SoftwareContextProfile, load_any_context_profile
from c1.context.software import DEPENDENCY_GAP, SoftwareSelection
from c1.context.software_render import (
    render_software_markdown,
    render_software_structured,
    section_labels,
)
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.software.service import Target

S = "urn:c1:ns:software#"
C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ROOT = Path(__file__).resolve().parents[3]


def lit(value: str, datatype: str = "string") -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + datatype)


def node(identifier: str, cls: str, properties: Mapping[str, Sequence[Any]]) -> NodeRecord:
    return NodeRecord(
        id=identifier,
        types=[cls],
        properties={key: list(value) for key, value in properties.items()},
    )


class Store:
    def __init__(self) -> None:
        self.records: dict[str, NodeRecord] = {}

    def add(self, record: NodeRecord) -> str:
        self.records[record.id] = record
        return record.id

    def claim(
        self,
        key: str,
        subject: str,
        predicate: str,
        obj: str,
        *,
        part: str,
        revision: str,
        quote: str | None = None,
    ) -> str:
        evidence = f"urn:t:evidence/{key}"
        claim = f"urn:t:assertion/{key}"
        properties: dict[str, list[Any]] = {
            C1 + "assertionRef": [claim],
            OA + "hasSource": [part],
            C1 + "sourceRevision": [lit(revision)],
        }
        if quote is not None:
            selector = self.add(
                node(
                    f"urn:t:selector/{key}",
                    C1 + "Selector",
                    {C1 + "selectorKind": [lit("TextQuoteSelector")], OA + "exact": [lit(quote)]},
                )
            )
            properties[OA + "hasSelector"] = [selector]
        self.add(NodeRecord(id=evidence, types=[C1 + "Evidence"], properties=properties))
        return self.add(
            node(
                claim,
                C1 + "Assertion",
                {
                    RDF + "subject": [subject],
                    RDF + "predicate": [S + predicate],
                    RDF + "object": [obj],
                    C1 + "origin": [lit("imported")],
                    C1 + "lifecycle": [lit("active")],
                    C1 + "evidence": [evidence],
                },
            )
        )


def fixture() -> tuple[Store, Target, dict[str, str]]:
    store = Store()
    ids: dict[str, str] = {}
    repo = store.add(node("urn:t:repo", S + "CodeRepository", {SKOS + "prefLabel": [lit("repo")]}))
    for key, commit in (("s1", "c1"), ("s2", "c2")):
        ids[key] = store.add(
            node(
                f"urn:t:{key}",
                S + "SourceSnapshot",
                {
                    S + "repositoryRef": [repo],
                    S + "commitId": [lit(commit)],
                    SKOS + "prefLabel": [lit(key)],
                },
            )
        )
    for key, commit in (("file1", "c1"), ("file2", "c2"), ("doc", "c1")):
        ids[key] = store.add(
            node(
                f"urn:t:{key}",
                C1 + "Document",
                {
                    DCT + "title": [lit({"doc": "docs/rule.md"}.get(key, "pkg/api.py"))],
                    C1 + "sourceRevision": [lit(commit)],
                    C1 + "contentDigest": [lit("sha256:" + key)],
                },
            )
        )
    parts = {
        "main": ("file1", "code-unit:python", "def main():\n    return helper(0)\n", "2"),
        "helper": ("file1", "code-unit:python", "def helper(x):\n    return x >= 0\n", "1"),
        "header": ("file1", "code:python", "import os\n", "0"),
        "main2": ("file2", "code-unit:python", "def main():\n    return helper(1)\n", "1"),
        "rule": ("doc", "text", "Zero is rejected.\n", "1"),
    }
    for key, (document, kind, text, order) in parts.items():
        ids[key] = store.add(
            node(
                f"urn:t:part/{key}",
                C1 + "DocumentPart",
                {
                    C1 + "partOfDocument": [ids[document]],
                    C1 + "partKind": [lit(kind)],
                    C1 + "text": [lit(text)],
                    C1 + "orderKey": [lit(order)],
                },
            )
        )
    for key in ("main", "helper"):
        ids[f"sym-{key}"] = store.add(
            node(f"urn:t:symbol/{key}", S + "CodeSymbol", {SKOS + "prefLabel": [lit("pkg." + key)]})
        )

    def occurrence(
        key: str, symbol: str, snapshot: str, part: str, file: str, line: int, roles: list[str]
    ) -> None:
        store.add(
            node(
                f"urn:t:occ/{key}",
                S + "SymbolOccurrence",
                {
                    S + "symbolRef": [ids[symbol]],
                    S + "snapshotRef": [ids[snapshot]],
                    S + "partRef": [ids[part]],
                    S + "fileRef": [ids[file]],
                    S + "role": [lit(role) for role in roles],
                    S + "startLine": [lit(str(line), "integer")],
                    S + "startCharacter": [lit("4", "integer")],
                    S + "endLine": [lit(str(line), "integer")],
                    S + "endCharacter": [lit("8", "integer")],
                    S + "positionEncoding": [lit("utf-8")],
                },
            )
        )

    occurrence("main-def", "sym-main", "s1", "main", "file1", 5, ["definition"])
    occurrence("helper-def", "sym-helper", "s1", "helper", "file1", 2, ["definition"])
    occurrence("helper-ref", "sym-helper", "s1", "main", "file1", 6, ["reference"])
    occurrence("main-def-2", "sym-main", "s2", "main2", "file2", 1, ["definition"])
    ids["op"] = store.add(
        node(
            "urn:t:op",
            S + "InterfaceOperation",
            {S + "operationId": [lit("run")], SKOS + "prefLabel": [lit("run")]},
        )
    )
    store.claim(
        "impl", ids["sym-main"], "implementsOperation", ids["op"], part=ids["main"], revision="c1"
    )
    store.claim(
        "describes", ids["doc"], "describesSnapshot", ids["s1"], part=ids["rule"], revision="c1"
    )
    store.claim("documents", ids["doc"], "documents", ids["op"], part=ids["rule"], revision="c1")
    store.claim(
        "discrepancy",
        ids["helper"],
        "discrepancy",
        ids["rule"],
        part=ids["helper"],
        revision="c1",
        quote="x >= 0",
    )
    ids["case"] = store.add(node("urn:t:case", S + "TestCase", {SKOS + "prefLabel": [lit("case")]}))
    store.claim("verifies", ids["case"], "verifies", ids["op"], part=ids["main"], revision="c1")
    ids["config"] = store.add(
        node("urn:t:config", S + "Configuration", {S + "configurationName": [lit("default")]})
    )
    ids["other-config"] = store.add(
        node("urn:t:config2", S + "Configuration", {S + "configurationName": [lit("other")]})
    )
    runs = {
        "matching": (["s1"], "config", "live", "fail"),
        "other-snapshot": (["s2"], "config", "live", "pass"),
        "other-config": (["s1"], "other-config", "live", "pass"),
        "mocked": (["s1"], "config", "mocked", "pass"),
    }
    for key, (snapshots, configuration, mode, result) in runs.items():
        ids[f"run-{key}"] = store.add(
            node(
                f"urn:t:run/{key}",
                S + "TestRun",
                {
                    S + "testCaseRef": [ids["case"]],
                    S + "snapshotRef": [ids[item] for item in snapshots],
                    S + "configurationRef": [ids[configuration]],
                    S + "integrationMode": [lit(mode)],
                    S + "result": [lit(result)],
                },
            )
        )
    target = Target({ids["s1"]: store.records[ids["s1"]]}, configurations=[ids["config"]])
    return store, target, ids


def profile(**changes: Any) -> SoftwareContextProfile:
    value = load_any_context_profile(ROOT / "profiles/context/test-development.json")
    assert isinstance(value, SoftwareContextProfile)
    if not changes:
        return value
    data = value.model_dump(mode="json")
    data["software"].update(changes)
    return SoftwareContextProfile.model_validate(data)


def select(store: Store, target: Target, anchor: str, **changes: Any) -> SoftwareSelection:
    selection = SoftwareSelection(
        store.records,
        target,
        store.records[anchor],
        profile(**changes),
        deadline=time.monotonic() + 30,
    )
    assert selection.build()["outcome"] == "resolved"
    return selection


def test_selection_is_pinned_ordered_and_labelled() -> None:
    store, target, ids = fixture()
    selection = select(store, target, ids["sym-main"])
    kinds = [(unit["section"], unit["kind"], unit.get("part_id")) for unit in selection.units]
    assert kinds[:3] == [
        ("normative", "documentation-part", ids["rule"]),
        ("implementation", "code-unit", ids["main"]),
        ("implementation", "dependency-unit", ids["helper"]),
    ]
    assert all(unit.get("commit") in {None, "c1"} for unit in selection.units)
    assert ids["main2"] not in {unit.get("part_id") for unit in selection.units}
    runs = {unit["run_id"]: unit for unit in selection.units if unit["kind"] == "test-run"}
    assert runs[ids["run-matching"]]["match"] == "matching"
    assert runs[ids["run-other-snapshot"]]["match"] == "other-target"
    assert runs[ids["run-other-config"]]["match"] == "other-target"
    assert runs[ids["run-mocked"]]["integration_mode"] == "mocked"
    assert not any(unit["integration_evidence"] for unit in runs.values())
    test = next(unit for unit in selection.units if unit["kind"] == "test-definition")
    assert test["status"] == "matching-run" and test["matching_results"] == ["fail", "pass"]
    discrepancy = next(unit for unit in selection.units if unit["kind"] == "discrepancy")
    assert discrepancy["implementation_part"] == ids["helper"]
    assert [c.get("quote") for c in discrepancy["citations"]] == ["x >= 0"]
    assert {"kind": "dependencies", "message": DEPENDENCY_GAP} in selection.gaps
    # The same records in another insertion order give the same selection.
    reordered = Store()
    for key in reversed(list(store.records)):
        reordered.add(store.records[key])
    assert select(reordered, target, ids["sym-main"]).units == selection.units


def test_no_definition_in_target_is_unresolved_not_substituted() -> None:
    store, target, ids = fixture()
    other = Target({ids["s2"]: store.records[ids["s2"]]})
    del store.records["urn:t:occ/main-def-2"]
    selection = SoftwareSelection(
        store.records,
        other,
        store.records[ids["sym-main"]],
        profile(),
        deadline=time.monotonic() + 30,
    )
    assert selection.build() == {"outcome": "unresolved", "reason": "no-definition-in-target"}


def test_unreadable_dependency_leaves_only_the_fixed_gap() -> None:
    store, target, ids = fixture()
    visible = select(store, target, ids["sym-main"])
    for key in ("urn:t:occ/helper-ref",):
        del store.records[key]
    hidden = select(store, target, ids["sym-main"])
    assert ids["helper"] not in {unit.get("part_id") for unit in hidden.units}
    assert hidden.gaps == [gap for gap in visible.gaps if gap["kind"] != "dependency-limit"]
    assert select(store, target, ids["sym-main"], dependency_depth=0).units == hidden.units


def test_dependency_limit_is_reported() -> None:
    store, target, ids = fixture()
    limited = select(store, target, ids["sym-main"], max_dependencies=0)
    assert ids["helper"] not in {unit.get("part_id") for unit in limited.units}
    assert any(gap["kind"] == "dependency-limit" for gap in limited.gaps)


def _page(selection: SoftwareSelection, goal: str) -> dict[str, Any]:
    base = {
        "interpretation": {"goal": goal, "revision": "r"},
        "target": {"snapshots": []},
        "gaps": selection.gaps,
        "anchor_label": "pkg.main",
    }
    return build_page(
        base,
        prepare_units(selection.units),
        maximum=524288,
        cursor_for_offset=lambda end: None,
        render_structured=render_software_structured,
        render_markdown=render_software_markdown,
    )


def test_rendering_labels_completeness_and_goal_only_changes_labels() -> None:
    store, target, ids = fixture()
    selection = select(store, target, ids["sym-main"])
    conformance = _page(selection, "conformance")
    characterization = _page(selection, "characterization")
    markdown = conformance["markdown"]
    assert "```python complete unit\ndef main():" in markdown
    assert conformance["structured"]["sections"] == characterization["structured"]["sections"]
    labels, other = section_labels("conformance"), section_labels("characterization")
    assert {key for key in labels if labels[key] != other[key]} == {"normative", "implementation"}
    assert "## " + _safe(labels["normative"]) in markdown
    assert "## " + _safe(other["normative"]) in characterization["markdown"]


def test_excerpt_parts_are_labelled_excerpt() -> None:
    store, target, ids = fixture()
    record = store.records["urn:t:occ/main-def"]
    properties = dict(record.properties)
    properties[S + "partRef"] = [ids["header"]]
    store.records[record.id] = NodeRecord(id=record.id, types=record.types, properties=properties)
    selection = select(store, target, ids["sym-main"])
    unit = next(unit for unit in selection.units if unit["kind"] == "code-unit")
    assert unit["code_completeness"] == "excerpt"
    assert "```python excerpt\nimport os" in _page(selection, "conformance")["markdown"]


def test_profile_grammar_is_closed() -> None:
    with pytest.raises(ValueError):
        profile(role_map={"code-unit": "structural"})
    with pytest.raises(ValueError):
        profile(max_dependencies=21)
    with pytest.raises(ValueError):
        profile(sections=["interpretation"])
