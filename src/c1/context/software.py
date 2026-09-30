"""Test-development selection over one authorized snapshot (M09 D4–D7).

Everything here reads only the request's authorized records and the target
already resolved from them. Selection is deterministic and bounded; it never
infers a relationship, never substitutes another snapshot for a missing
definition, and never reveals whether an unreturned dependency exists.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from c1.context.errors import ContextError
from c1.context.profiles import SoftwareContextProfile
from c1.context.resolve import candidate
from c1.model.keywords import normalize
from c1.model.nodes import NodeRecord
from c1.software.service import (
    C1,
    DCT,
    OA,
    PROV,
    RDF,
    SKOS,
    S,
    Target,
    _int,
    _iri,
    _iris,
    _text,
    _texts,
)

ANCHOR_CLASSES = {
    "symbol": S + "CodeSymbol",
    "capability": S + "Capability",
    "operation": S + "InterfaceOperation",
}
# Fixed section order of the test-development template (D2).
UNIT_SECTIONS = (
    "normative",
    "implementation",
    "interfaces",
    "tests",
    "runs",
    "fixtures",
    "instructions",
    "discrepancies",
)
DEPENDENCY_GAP = (
    "Definitions referenced by the returned code that are not listed in this package "
    "are not included in the returned material."
)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ContextError(503, "C1-CX-014", "time_budget")


def _identifier(kind: str, *parts: str) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"urn:c1:context:{kind}:" + hashlib.sha256(encoded).hexdigest()


def _label(node: NodeRecord | None) -> str | None:
    if node is None:
        return None
    return _text(node, SKOS + "prefLabel") or _text(node, DCT + "title") or node.id


def _active(node: NodeRecord) -> bool:
    return (_text(node, C1 + "lifecycle") or "active") == "active"


def resolve_software_anchor(
    records: dict[str, NodeRecord],
    selector: Any,
    profile: SoftwareContextProfile,
) -> dict[str, Any]:
    """Exact selection among readable anchors; hidden and unknown IDs answer alike."""
    classes = {ANCHOR_CLASSES[kind] for kind in profile.software.anchor_kinds}
    eligible = {
        key: node
        for key, node in records.items()
        if classes.intersection(node.types) and _active(node)
    }
    if hasattr(selector, "id"):
        node = eligible.get(selector.id)
        if node is None:
            raise ContextError(404, "C1-CX-404", "not_found")
        return {"outcome": "resolved", "anchor": candidate(node)}
    from c1.context.resolve import label_matches

    matches = [
        candidate(node) for _, node in sorted(eligible.items()) if label_matches(node, selector)
    ]
    if len(matches) == 1:
        return {"outcome": "resolved", "anchor": matches[0]}
    return {"outcome": "ambiguous" if matches else "unresolved", "candidates": matches}


@dataclass
class _Index:
    records: dict[str, NodeRecord]
    target: Target
    assertions: dict[str, list[NodeRecord]] = field(default_factory=lambda: defaultdict(list))
    definitions: dict[tuple[str, str], list[NodeRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    in_part: dict[str, list[NodeRecord]] = field(default_factory=lambda: defaultdict(list))
    parts_of: dict[str, list[NodeRecord]] = field(default_factory=lambda: defaultdict(list))

    def __post_init__(self) -> None:
        for node in self.records.values():
            if C1 + "Assertion" in node.types and _active(node):
                predicate = _iri(node, RDF + "predicate")
                if predicate is not None:
                    self.assertions[predicate].append(node)
            elif S + "SymbolOccurrence" in node.types:
                snapshot = _iri(node, S + "snapshotRef")
                if snapshot not in self.target.snapshots:
                    continue
                symbol = _iri(node, S + "symbolRef")
                part = _iri(node, S + "partRef")
                if "definition" in _texts(node, S + "role") and symbol is not None:
                    self.definitions[(symbol, str(snapshot))].append(node)
                if part is not None:
                    self.in_part[part].append(node)
            elif C1 + "DocumentPart" in node.types:
                document = _iri(node, C1 + "partOfDocument")
                if document is not None:
                    self.parts_of[document].append(node)
        for values in (*self.assertions.values(), *self.definitions.values()):
            values.sort(key=lambda item: item.id)
        for values in self.in_part.values():
            values.sort(key=_occurrence_order)
        for values in self.parts_of.values():
            values.sort(key=lambda item: (_text(item, C1 + "orderKey") or "", item.id))

    @property
    def commits(self) -> dict[str, str]:
        return self.target.commits

    def claims(self, predicate: str) -> list[NodeRecord]:
        return self.assertions.get(S + predicate, [])

    def pinned(self, claim: NodeRecord) -> bool:
        """The claim has readable evidence recorded at a target commit."""
        for evidence_id in _iris(claim, C1 + "evidence"):
            evidence = self.records.get(evidence_id)
            if evidence is not None and _text(evidence, C1 + "sourceRevision") in self.commits:
                return True
        return False

    def typed(self, identifier: str | None, cls: str) -> NodeRecord | None:
        node = self.records.get(identifier) if identifier else None
        return node if node is not None and cls in node.types else None

    def definition(self, symbol: str) -> tuple[NodeRecord, NodeRecord, NodeRecord] | None:
        """The symbol's definition occurrence, part, and file in a target snapshot."""
        for snapshot in sorted(self.target.snapshots):
            for occurrence in sorted(
                self.definitions.get((symbol, snapshot), []), key=_occurrence_order
            ):
                part = self.typed(_iri(occurrence, S + "partRef"), C1 + "DocumentPart")
                document = self.typed(_iri(occurrence, S + "fileRef"), C1 + "Document")
                if (
                    part is not None
                    and document is not None
                    and _iri(part, C1 + "partOfDocument") == document.id
                    and _text(document, C1 + "sourceRevision") in self.commits
                ):
                    return occurrence, part, document
        return None


def _occurrence_order(node: NodeRecord) -> tuple[int, int, str]:
    return (_int(node, S + "startLine"), _int(node, S + "startCharacter"), node.id)


class SoftwareSelection:
    """Build test-development units; every step reads only authorized records."""

    def __init__(
        self,
        records: dict[str, NodeRecord],
        target: Target,
        anchor: NodeRecord,
        profile: SoftwareContextProfile,
        *,
        deadline: float,
    ) -> None:
        self.index = _Index(records, target)
        self.records = records
        self.target = target
        self.anchor = anchor
        self.profile = profile
        self.settings = profile.software
        self.deadline = deadline
        self.units: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = []
        self.selected_parts: set[str] = set()
        self._unit_ids: set[str] = set()

    # helpers ---------------------------------------------------------------------------

    def _role(self, kind: str) -> str:
        return self.settings.role_map[kind]

    def _part_view(self, part: NodeRecord, document: NodeRecord) -> dict[str, Any]:
        kind = _text(part, C1 + "partKind") or "text"
        base, _, language = kind.partition(":")
        commit = _text(document, C1 + "sourceRevision")
        result: dict[str, Any] = {
            "part_id": part.id,
            "document_id": document.id,
            "path": _text(document, DCT + "title"),
            "commit": commit,
            "target_member": self.index.commits.get(str(commit)),
            "part_kind": kind,
            "text": _text(part, C1 + "text") or "",
        }
        if base in {"code", "code-unit"}:
            result["language"] = language or "text"
            result["code_completeness"] = "complete-unit" if base == "code-unit" else "excerpt"
        return result

    def _part_citation(self, part: NodeRecord, document: NodeRecord) -> dict[str, Any]:
        return {
            "id": _identifier("citation", "part", part.id),
            "kind": "part",
            "part_id": part.id,
            "document_id": document.id,
            "path": _text(document, DCT + "title"),
            "commit": _text(document, C1 + "sourceRevision"),
            "content_digest": _text(document, C1 + "contentDigest"),
        }

    def _evidence_citations(
        self, claim: NodeRecord, dependencies: set[str]
    ) -> list[dict[str, Any]]:
        result = []
        for evidence_id in sorted(_iris(claim, C1 + "evidence")):
            evidence = self.records.get(evidence_id)
            if evidence is None or _iri(evidence, C1 + "assertionRef") != claim.id:
                continue
            part = self.index.typed(_iri(evidence, OA + "hasSource"), C1 + "DocumentPart")
            document = (
                self.index.typed(_iri(part, C1 + "partOfDocument"), C1 + "Document")
                if part is not None
                else None
            )
            if part is None or document is None:
                continue
            citation = {
                **self._part_citation(part, document),
                "id": _identifier("citation", "evidence", evidence.id),
                "kind": "evidence",
                "evidence_id": evidence.id,
                "evidence_revision": _text(evidence, C1 + "sourceRevision"),
            }
            selector = self.records.get(_iri(evidence, OA + "hasSelector") or "")
            if selector is not None and _text(selector, C1 + "selectorKind") == "TextQuoteSelector":
                exact = _text(selector, OA + "exact")
                if exact is not None and exact in (_text(part, C1 + "text") or ""):
                    citation["quote"] = exact
                    dependencies.add(selector.id)
            dependencies.update((evidence.id, part.id, document.id))
            result.append(citation)
        return result

    def _claim_view(self, claim: NodeRecord, dependencies: set[str]) -> dict[str, Any]:
        dependencies.add(claim.id)
        return {
            "assertion_id": claim.id,
            "predicate": _iri(claim, RDF + "predicate"),
            "origin": _text(claim, C1 + "origin"),
            "review_state": _text(claim, C1 + "reviewState") or "reported",
            "attributed_to": _iri(claim, PROV + "wasAttributedTo"),
            "generated_by": _iri(claim, PROV + "wasGeneratedBy"),
        }

    def _add(self, unit: dict[str, Any], order: tuple[Any, ...]) -> None:
        if unit["id"] in self._unit_ids:
            return
        self._unit_ids.add(unit["id"])
        unit["_order"] = (UNIT_SECTIONS.index(unit["section"]), *order)
        self.units.append(unit)

    def _part_unit(
        self,
        section: str,
        kind: str,
        part: NodeRecord,
        document: NodeRecord,
        order: tuple[Any, ...],
        dependencies: set[str],
        **extra: Any,
    ) -> None:
        unit_id = _identifier("unit", section, part.id)
        if unit_id in self._unit_ids:
            return
        self.selected_parts.add(part.id)
        dependencies.update((part.id, document.id))
        unit = {
            "id": unit_id,
            "section": section,
            "kind": kind,
            "role": self._role(kind),
            **self._part_view(part, document),
            **extra,
            "citations": [self._part_citation(part, document)],
            "_dependencies": sorted(dependencies),
        }
        self._add(unit, order)

    # selection -------------------------------------------------------------------------

    def target_symbols(self) -> list[NodeRecord]:
        anchor = self.anchor
        if S + "CodeSymbol" in anchor.types:
            candidates = [anchor]
        elif S + "Capability" in anchor.types:
            candidates = [
                node
                for claim in self.index.claims("implementsCapability")
                if _iri(claim, RDF + "object") == anchor.id
                and (node := self.index.typed(_iri(claim, RDF + "subject"), S + "CodeSymbol"))
            ]
        else:
            candidates = [
                node
                for claim in self.index.claims("implementsOperation")
                if _iri(claim, RDF + "object") == anchor.id
                and self.index.pinned(claim)
                and (node := self.index.typed(_iri(claim, RDF + "subject"), S + "CodeSymbol"))
            ]
        unique = {node.id: node for node in candidates if self.index.definition(node.id)}
        return sorted(unique.values(), key=lambda node: (normalize(_label(node) or ""), node.id))

    def build(self) -> dict[str, Any]:
        symbols = self.target_symbols()
        if not symbols:
            return {"outcome": "unresolved", "reason": "no-definition-in-target"}
        symbol_ids = {node.id for node in symbols}
        self._implementation(symbols, symbol_ids)
        operations = self._interfaces(symbol_ids)
        self._normative(symbol_ids, operations)
        cases = self._tests(symbol_ids, operations)
        self._fixtures(cases)
        self._instructions()
        self._discrepancies()
        self._incompleteness()
        self.units.sort(key=lambda unit: unit["_order"])
        for unit in self.units:
            del unit["_order"]
        return {"outcome": "resolved", "symbols": symbols}

    def _implementation(self, symbols: list[NodeRecord], symbol_ids: set[str]) -> None:
        member_order = {
            identifier: index for index, identifier in enumerate(sorted(self.target.snapshots))
        }
        # (1) target definitions and (2) direct dependencies in the same snapshot.
        definitions = []
        for rank, symbol in enumerate(symbols):
            _check_deadline(self.deadline)
            found = self.index.definition(symbol.id)
            assert found is not None
            occurrence, part, document = found
            definitions.append((symbol, occurrence, part, document))
            self._part_unit(
                "implementation",
                "code-unit",
                part,
                document,
                (member_order[str(_iri(occurrence, S + "snapshotRef"))], rank, part.id),
                {symbol.id, occurrence.id},
                symbol={"id": symbol.id, "label": _label(symbol)},
                range=_range(occurrence),
            )
        omitted = 0
        if self.settings.dependency_depth >= 1:
            dependencies_seen: list[tuple[NodeRecord, NodeRecord, NodeRecord, NodeRecord]] = []
            for _symbol, _occurrence, part, _document in definitions:
                for reference in self.index.in_part.get(part.id, []):
                    target_symbol = _iri(reference, S + "symbolRef")
                    if (
                        target_symbol is None
                        or target_symbol in symbol_ids
                        or "definition" in _texts(reference, S + "role")
                    ):
                        continue
                    symbol_node = self.index.typed(target_symbol, S + "CodeSymbol")
                    found = self.index.definition(target_symbol) if symbol_node else None
                    if symbol_node is None or found is None:
                        continue
                    if _iri(found[0], S + "snapshotRef") != _iri(reference, S + "snapshotRef"):
                        continue
                    if (
                        any(item[2].id == found[1].id for item in dependencies_seen)
                        or found[1].id in self.selected_parts
                    ):
                        continue
                    dependencies_seen.append((symbol_node, reference, found[1], found[2]))
            for rank, (symbol_node, reference, part, document) in enumerate(dependencies_seen):
                if rank >= self.settings.max_dependencies:
                    omitted += 1
                    continue
                definition = self.index.definition(symbol_node.id)
                assert definition is not None
                self._part_unit(
                    "implementation",
                    "dependency-unit",
                    part,
                    document,
                    (
                        member_order[str(_iri(reference, S + "snapshotRef"))],
                        len(symbols) + rank,
                        part.id,
                    ),
                    {symbol_node.id, reference.id, definition[0].id},
                    symbol={"id": symbol_node.id, "label": _label(symbol_node)},
                    range=_range(definition[0]),
                    referenced_at=_range(reference),
                )
        self.gaps.append({"kind": "dependencies", "message": DEPENDENCY_GAP})
        if omitted:
            self.gaps.append(
                {
                    "kind": "dependency-limit",
                    "message": f"{omitted} further referenced definitions were omitted "
                    "by the profile limit.",
                }
            )

    def _interfaces(self, symbol_ids: set[str]) -> dict[str, NodeRecord]:
        # (3) interfaces.
        operations: dict[str, NodeRecord] = {}
        operation_claims: dict[str, list[NodeRecord]] = defaultdict(list)
        if S + "InterfaceOperation" in self.anchor.types:
            operations[self.anchor.id] = self.anchor
        for predicate in ("implementsOperation", "declaredCall"):
            for claim in self.index.claims(predicate):
                if _iri(claim, RDF + "subject") in symbol_ids and self.index.pinned(claim):
                    operation = self.index.typed(
                        _iri(claim, RDF + "object"), S + "InterfaceOperation"
                    )
                    if operation is not None:
                        operations[operation.id] = operation
                        operation_claims[operation.id].append(claim)
        for operation in sorted(
            operations.values(), key=lambda node: (_text(node, S + "operationId") or "", node.id)
        ):
            dependencies = {operation.id}
            basis = [
                self._claim_view(claim, dependencies) for claim in operation_claims[operation.id]
            ]
            citations = [
                citation
                for claim in operation_claims[operation.id]
                for citation in self._evidence_citations(claim, dependencies)
            ]
            provider = self.records.get(_iri(operation, S + "providerRef") or "")
            if provider is not None:
                dependencies.add(provider.id)
            self._add(
                {
                    "id": _identifier("unit", "interfaces", operation.id),
                    "section": "interfaces",
                    "kind": "operation",
                    "role": self._role("operation"),
                    "operation": {
                        "id": operation.id,
                        "operation_id": _text(operation, S + "operationId"),
                        "http_method": _text(operation, S + "httpMethod"),
                        "path_template": _text(operation, S + "pathTemplate"),
                        "provider": {"id": provider.id, "label": _label(provider)}
                        if provider is not None
                        else None,
                    },
                    "basis": basis,
                    "citations": citations,
                    "_dependencies": sorted(dependencies),
                },
                (_text(operation, S + "operationId") or "", operation.id),
            )

        return operations

    def _normative(self, symbol_ids: set[str], operations: dict[str, NodeRecord]) -> None:
        # (4) normative: applicable documentation and the target contract parts.
        documented = {self.anchor.id, *symbol_ids, *operations}
        applicable: dict[str, set[str]] = defaultdict(set)
        for claim in self.index.claims("describesSnapshot"):
            if _iri(claim, RDF + "object") in self.target.snapshots:
                applicable[str(_iri(claim, RDF + "subject"))].add(claim.id)
        normative_documents: dict[str, set[str]] = defaultdict(set)
        for claim in self.index.claims("documents"):
            subject = str(_iri(claim, RDF + "subject"))
            if _iri(claim, RDF + "object") in documented and subject in applicable:
                normative_documents[subject].update({claim.id, *applicable[subject]})
        for operation_id in operations:
            for claim in self.index.claims("specifiedIn"):
                if _iri(claim, RDF + "subject") != operation_id:
                    continue
                contract = str(_iri(claim, RDF + "object"))
                document = self.index.typed(contract, C1 + "Document")
                if document is None:
                    continue
                chosen = (
                    contract in self.target.contracts
                    if self.target.contracts
                    else _text(document, C1 + "sourceRevision") in self.index.commits
                )
                if chosen:
                    normative_documents[contract].add(claim.id)
        for document_id in sorted(
            normative_documents,
            key=lambda item: (_text(self.records[item], DCT + "title") or "", item),
        ):
            document = self.index.typed(document_id, C1 + "Document")
            if document is None:
                continue
            for part in self.index.parts_of.get(document.id, []):
                kind = (
                    "contract-part"
                    if (_text(part, C1 + "partKind") or "").startswith("code")
                    else "documentation-part"
                )
                self._part_unit(
                    "normative",
                    kind,
                    part,
                    document,
                    (
                        _text(document, DCT + "title") or "",
                        document.id,
                        _text(part, C1 + "orderKey") or "",
                        part.id,
                    ),
                    set(normative_documents[document_id]),
                )
        if not any(unit["section"] == "normative" for unit in self.units):
            self.gaps.append(
                {
                    "kind": "normative",
                    "message": "No documentation or contract applicable to the target "
                    "is in the returned material.",
                }
            )

    def _tests(self, symbol_ids: set[str], operations: dict[str, NodeRecord]) -> list[str]:
        # (5) tests and (6) runs.
        capabilities = {
            str(_iri(claim, RDF + "object"))
            for claim in self.index.claims("implementsCapability")
            if _iri(claim, RDF + "subject") in symbol_ids
        }
        verified = {self.anchor.id, *symbol_ids, *operations, *capabilities}
        cases: dict[str, set[str]] = defaultdict(set)
        for claim in self.index.claims("verifies"):
            case = self.index.typed(_iri(claim, RDF + "subject"), S + "TestCase")
            if case is not None and _iri(claim, RDF + "object") in verified:
                cases[case.id].add(claim.id)
        defined_at: dict[str, tuple[NodeRecord, NodeRecord, NodeRecord, NodeRecord]] = {}
        for claim in self.index.claims("definedAt"):
            case = self.index.typed(_iri(claim, RDF + "subject"), S + "TestCase")
            occurrence = self.index.typed(_iri(claim, RDF + "object"), S + "SymbolOccurrence")
            if case is None or occurrence is None:
                continue
            if _iri(occurrence, S + "snapshotRef") not in self.target.snapshots:
                continue
            part = self.index.typed(_iri(occurrence, S + "partRef"), C1 + "DocumentPart")
            document = self.index.typed(_iri(occurrence, S + "fileRef"), C1 + "Document")
            if part is None or document is None:
                continue
            defined_at[case.id] = (claim, occurrence, part, document)
            if any(
                _iri(reference, S + "symbolRef") in symbol_ids
                for reference in self.index.in_part.get(part.id, [])
            ):
                cases[case.id].add(claim.id)
        ordered_cases = sorted(
            cases,
            key=lambda item: (normalize(_label(self.records[item]) or ""), item),
        )
        if len(ordered_cases) > self.settings.max_tests:
            self.gaps.append(
                {
                    "kind": "test-limit",
                    "message": f"{len(ordered_cases) - self.settings.max_tests} further "
                    "test cases were omitted by the profile limit.",
                }
            )
            ordered_cases = ordered_cases[: self.settings.max_tests]
        runs_by_case: dict[str, list[NodeRecord]] = defaultdict(list)
        for node in self.records.values():
            if S + "TestRun" in node.types and _iri(node, S + "testCaseRef") in ordered_cases:
                runs_by_case[str(_iri(node, S + "testCaseRef"))].append(node)
        run_views: list[tuple[str, NodeRecord, dict[str, Any]]] = []
        for rank, case_id in enumerate(ordered_cases):
            case = self.records[case_id]
            views = [self._run_view(run) for run in runs_by_case.get(case_id, [])]
            matching = sorted(
                view["result"] or "unknown" for view in views if view["match"] == "matching"
            )
            status = "matching-run" if matching else "definition-only"
            dependencies = {case.id, *cases[case_id]}
            verifies = []
            for claim in self.index.claims("verifies"):
                if _iri(claim, RDF + "subject") == case.id:
                    target = self.records.get(_iri(claim, RDF + "object") or "")
                    if target is not None:
                        dependencies.update((claim.id, target.id))
                        verifies.append({"id": target.id, "label": _label(target)})
            extra = {
                "test_case": {"id": case.id, "label": _label(case)},
                "status": status,
                "matching_results": matching,
                "verifies": sorted(verifies, key=lambda item: str(item["id"])),
            }
            definition = defined_at.get(case_id)
            if definition is not None:
                claim, occurrence, part, document = definition
                dependencies.update((claim.id, occurrence.id))
                self._part_unit(
                    "tests",
                    "test-definition",
                    part,
                    document,
                    (rank, case.id),
                    dependencies,
                    **extra,
                )
            else:
                self._add(
                    {
                        "id": _identifier("unit", "tests", case.id),
                        "section": "tests",
                        "kind": "test-definition",
                        "role": self._role("test-definition"),
                        **extra,
                        "definition": None,
                        "citations": [],
                        "_dependencies": sorted(dependencies),
                    },
                    (rank, case.id),
                )
            for run in runs_by_case.get(case_id, []):
                run_views.append((case_id, run, self._run_view(run)))
        run_views.sort(
            key=lambda item: (
                ordered_cases.index(item[0]),
                0 if item[2]["match"] == "matching" else 1,
                item[2]["started_at"] or "",
                item[1].id,
            )
        )
        if len(run_views) > self.settings.max_runs:
            self.gaps.append(
                {
                    "kind": "run-limit",
                    "message": f"{len(run_views) - self.settings.max_runs} further "
                    "test runs were omitted by the profile limit.",
                }
            )
            run_views = run_views[: self.settings.max_runs]
        for rank, (_case_id, run, view) in enumerate(run_views):
            dependencies = set(view.pop("_dependencies"))
            citations = view.pop("_citations")
            self._add(
                {
                    "id": _identifier("unit", "runs", run.id),
                    "section": "runs",
                    "kind": "test-run",
                    "role": self._role("test-run"),
                    **view,
                    "citations": citations,
                    "_dependencies": sorted(dependencies),
                },
                (rank, run.id),
            )

        return ordered_cases

    def _fixtures(self, ordered_cases: list[str]) -> None:
        # (7) fixtures.
        fixture_parts = []
        for claim in self.index.claims("fixtureOf"):
            if _iri(claim, RDF + "object") not in ordered_cases:
                continue
            symbol_node = self.index.typed(_iri(claim, RDF + "subject"), S + "CodeSymbol")
            found = self.index.definition(symbol_node.id) if symbol_node is not None else None
            if symbol_node is None or found is None:
                continue
            fixture_parts.append((symbol_node, claim, found))
        fixture_parts.sort(
            key=lambda item: (normalize(_label(item[0]) or ""), item[0].id, item[1].id)
        )
        for symbol_node, claim, (occurrence, part, document) in fixture_parts:
            dependencies = {symbol_node.id, occurrence.id}
            basis = [self._claim_view(claim, dependencies)]
            self._part_unit(
                "fixtures",
                "fixture-unit",
                part,
                document,
                (normalize(_label(symbol_node) or ""), symbol_node.id),
                dependencies,
                symbol={"id": symbol_node.id, "label": _label(symbol_node)},
                basis=basis,
                fixture_for=str(_iri(claim, RDF + "object")),
            )

    def _instructions(self) -> None:
        # (8) execution instructions: untrusted declared text, never executed.
        repositories = {
            _iri(record, S + "repositoryRef") for record in self.target.snapshots.values()
        }
        instructions = []
        for claim in self.index.claims("executionInstructions"):
            if _iri(claim, RDF + "object") not in repositories:
                continue
            document = self.index.typed(_iri(claim, RDF + "subject"), C1 + "Document")
            if document is None or _text(document, C1 + "sourceRevision") not in self.index.commits:
                continue
            for evidence_id in _iris(claim, C1 + "evidence"):
                evidence = self.records.get(evidence_id)
                if evidence is None:
                    continue
                part = self.index.typed(_iri(evidence, OA + "hasSource"), C1 + "DocumentPart")
                if part is None or _iri(part, C1 + "partOfDocument") != document.id:
                    continue
                instructions.append((document, part, claim, evidence))
        instructions.sort(
            key=lambda item: (
                _text(item[0], DCT + "title") or "",
                item[0].id,
                _text(item[1], C1 + "orderKey") or "",
                item[1].id,
            )
        )
        for document, part, claim, evidence in instructions:
            dependencies = {evidence.id}
            basis = [self._claim_view(claim, dependencies)]
            self._part_unit(
                "instructions",
                "instruction-part",
                part,
                document,
                (
                    _text(document, DCT + "title") or "",
                    document.id,
                    _text(part, C1 + "orderKey") or "",
                ),
                dependencies,
                basis=basis,
                untrusted=True,
            )

    def _discrepancies(self) -> None:
        # (9) recorded discrepancies touching a selected part.
        for claim in self.index.claims("discrepancy"):
            subject = _iri(claim, RDF + "subject")
            obj = _iri(claim, RDF + "object")
            if subject not in self.selected_parts and obj not in self.selected_parts:
                continue
            dependencies: set[str] = set()
            view = self._claim_view(claim, dependencies)
            citations = self._evidence_citations(claim, dependencies)
            self._add(
                {
                    "id": _identifier("unit", "discrepancies", claim.id),
                    "section": "discrepancies",
                    "kind": "discrepancy",
                    "role": self._role("discrepancy"),
                    **view,
                    "implementation_part": subject,
                    "normative_part": obj,
                    "citations": citations,
                    "_dependencies": sorted(dependencies | {str(subject), str(obj)}),
                },
                (claim.id,),
            )

    def _incompleteness(self) -> None:
        # Readable incompleteness recorded for the returned code files.
        files = {
            (unit["document_id"], unit["target_member"])
            for unit in self.units
            if unit["kind"] in {"code-unit", "dependency-unit"}
        }
        for node in sorted(self.records.values(), key=lambda item: item.id):
            if S + "UnresolvedReference" in node.types or S + "ImportIssue" in node.types:
                if (_iri(node, S + "fileRef"), _iri(node, S + "snapshotRef")) not in files:
                    continue
                file = self.records.get(_iri(node, S + "fileRef") or "")
                entry: dict[str, Any] = {
                    "record_id": node.id,
                    "path": _text(file, DCT + "title") if file is not None else None,
                    "target_member": _iri(node, S + "snapshotRef"),
                }
                if S + "UnresolvedReference" in node.types:
                    entry.update(
                        kind="unresolved-reference",
                        symbol_text=_text(node, S + "symbolText"),
                        reason=_text(node, S + "unresolvedReason"),
                        line=_int(node, S + "startLine"),
                        message="A reference in the returned code was not resolved "
                        "by the producer.",
                    )
                else:
                    entry.update(
                        kind="import-issue",
                        code=_text(node, S + "issueCode"),
                        severity=_text(node, S + "severity"),
                        message="The producer reported an issue for this file: "
                        + (_text(node, S + "issueMessage") or "no message"),
                    )
                self.gaps.append(entry)

    def _run_view(self, run: NodeRecord) -> dict[str, Any]:
        snapshots = _iris(run, S + "snapshotRef")
        configuration = _iri(run, S + "configurationRef")
        pinned = bool(snapshots) and set(snapshots) <= set(self.target.snapshots)
        configured = (
            configuration in self.target.configurations
            if self.target.configurations
            else configuration is None
        )
        match = "matching" if pinned and configured else "other-target"
        mode = _text(run, S + "integrationMode") or "unknown"
        repositories = {
            _iri(self.target.snapshots[item], S + "repositoryRef")
            for item in snapshots
            if item in self.target.snapshots
        }
        dependencies = {run.id}
        snapshot_views = []
        for identifier in sorted(snapshots):
            node = self.records.get(identifier)
            if node is not None:
                dependencies.add(identifier)
            snapshot_views.append(
                {
                    "id": identifier,
                    "commit": _text(node, S + "commitId") if node is not None else None,
                    "label": _label(node),
                }
            )
        configuration_node = self.records.get(configuration or "")
        mocked = []
        for identifier in sorted(_iris(run, S + "mockedProductRef")):
            node = self.records.get(identifier)
            mocked.append({"id": identifier, "label": _label(node)})
        exercised = []
        for claim in self.index.claims("exercised"):
            if _iri(claim, RDF + "subject") == run.id:
                operation = self.records.get(_iri(claim, RDF + "object") or "")
                if operation is not None:
                    dependencies.update((claim.id, operation.id))
                    exercised.append({"id": operation.id, "label": _label(operation)})
        citations = []
        report = self.index.typed(_iri(run, S + "reportRef"), C1 + "Document")
        if report is not None:
            parts = self.index.parts_of.get(report.id, [])
            if parts:
                citations.append(self._part_citation(parts[0], report))
                dependencies.update((report.id, parts[0].id))
        return {
            "run_id": run.id,
            "test_case": _iri(run, S + "testCaseRef"),
            "result": _text(run, S + "result"),
            "match": match,
            "integration_mode": mode,
            "mocked_products": mocked,
            "integration_evidence": match == "matching"
            and mode == "live"
            and len(repositories) >= 2,
            "snapshots": snapshot_views,
            "configuration": {
                "id": configuration,
                "name": _text(configuration_node, S + "configurationName")
                if configuration_node is not None
                else None,
            }
            if configuration
            else None,
            "started_at": _text(run, S + "startedAt"),
            "exercised": sorted(exercised, key=lambda item: item["id"]),
            "_dependencies": sorted(
                dependencies | ({configuration} if configuration_node else set())
            ),
            "_citations": citations,
        }


def _range(occurrence: NodeRecord) -> dict[str, Any]:
    return {
        "start_line": _int(occurrence, S + "startLine"),
        "start_character": _int(occurrence, S + "startCharacter"),
        "end_line": _int(occurrence, S + "endLine"),
        "end_character": _int(occurrence, S + "endCharacter"),
        "position_encoding": _text(occurrence, S + "positionEncoding"),
    }


def coverage_summary(records: dict[str, NodeRecord], target: Target) -> list[dict[str, Any]]:
    """Readable coverage records for the target snapshots; absent means unknown."""
    result = []
    for node in records.values():
        if S + "ImportCoverage" in node.types and _iri(node, S + "snapshotRef") in target.snapshots:
            result.append(
                {
                    "id": node.id,
                    "target_member": _iri(node, S + "snapshotRef"),
                    "method": _text(node, S + "importMethod"),
                    "state": _text(node, S + "coverageState"),
                }
            )
    return sorted(
        result, key=lambda item: (item["target_member"], item["method"] or "", item["id"])
    )
