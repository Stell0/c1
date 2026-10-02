"""Cross-software documentation-update selection (M11 D1–D5, D8; ADR-0022).

One authorized selection over the request's readable records gives, for a
target spanning at least two repositories:

* the structure of every candidate document, with each part's applicability
  relative to each target snapshot and every readable contributing record;
* each repository's responsibilities, the explicit interface contract and its
  links, configuration, labelled test runs, review candidates and recorded
  discrepancies, readable drafts with their lineage and publication state;
* compatibility per pair of target snapshots, `unknown` without a matching
  live run.

Nothing is inferred: absence of a readable declaration or record is `unknown`,
matching names never link, and no prose is written or judged.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from c1.context.profiles import TASK_TEMPLATES, SoftwareContextProfile
from c1.context.software import SoftwareSelection, _identifier, _label
from c1.model.nodes import NodeRecord
from c1.software.service import C1, DCT, PROV, RDF, S, Target, _iri, _iris, _text

STATES = ("contradicted", "not-applicable", "needs-review", "applicable")
# Most cautious first (D2); unknown is the absence of any readable input.
CAUTION = {state: rank for rank, state in enumerate(STATES)}
COMPATIBILITY_UNKNOWN = (
    "No matching live run covers this pair in the returned material; compatibility is unknown."
)
# M09 section names reused by inherited helpers map onto this template.
SECTION_ALIASES = {
    "implementation": "responsibilities",
    "interfaces": "interface-contract",
    "discrepancies": "changes",
}


class DocUpdateSelection(SoftwareSelection):
    def __init__(
        self,
        records: dict[str, NodeRecord],
        target: Target,
        anchor: NodeRecord,
        profile: SoftwareContextProfile,
        *,
        deadline: float,
    ) -> None:
        super().__init__(records, target, anchor, profile, deadline=deadline)
        self.sections = TASK_TEMPLATES["documentation-update"][0]

    def _add(self, unit: dict[str, Any], order: tuple[Any, ...]) -> None:
        unit["section"] = SECTION_ALIASES.get(unit["section"], unit["section"])
        if unit["id"] in self._unit_ids:
            return
        self._unit_ids.add(unit["id"])
        unit["_order"] = (self.sections.index(unit["section"]), *order)
        self.units.append(unit)

    def build(self) -> dict[str, Any]:
        operations, responsibilities = self._responsible()
        symbol_ids = set(responsibilities)
        if symbol_ids:
            symbols = sorted(
                (self.records[item] for item in symbol_ids),
                key=lambda node: (_label(node) or "", node.id),
            )
            self._implementation(symbols, symbol_ids)
        for unit in self.units:
            if unit["kind"] == "code-unit":
                kinds = responsibilities.get(unit["symbol"]["id"], [])
                unit["responsibility"] = sorted(kinds)
                unit["repository"] = _iri(self.records[unit["symbol"]["id"]], S + "repositoryRef")
        found = self._interfaces(symbol_ids)
        operations.update(found)
        self._contract(operations)
        documents = self._structure(set(operations) | symbol_ids)
        self._configuration()
        self._runs(operations)
        self._changes(documents)
        self._drafts(documents)
        self._compatibility()
        self.units.sort(key=lambda unit: unit["_order"])
        for unit in self.units:
            del unit["_order"]
        return {"outcome": "resolved", "symbols": []}

    # responsibilities and the interface contract ---------------------------------

    def _responsible(self) -> tuple[dict[str, NodeRecord], dict[str, list[str]]]:
        """Operations of the anchor and the symbols linked to them by explicit claims."""
        operations: dict[str, NodeRecord] = {}
        responsibilities: dict[str, list[str]] = defaultdict(list)
        if S + "InterfaceOperation" in self.anchor.types:
            operations[self.anchor.id] = self.anchor
        else:
            for implementer in self.target_symbols():
                responsibilities[implementer.id].append("implementsCapability")
            for predicate in ("implementsOperation", "declaredCall"):
                for claim in self.index.claims(predicate):
                    if _iri(claim, RDF + "subject") in responsibilities and self.index.pinned(
                        claim
                    ):
                        operation = self.index.typed(
                            _iri(claim, RDF + "object"), S + "InterfaceOperation"
                        )
                        if operation is not None:
                            operations[operation.id] = operation
        for predicate in ("implementsOperation", "declaredCall"):
            for claim in self.index.claims(predicate):
                symbol = self.index.typed(_iri(claim, RDF + "subject"), S + "CodeSymbol")
                if (
                    symbol is not None
                    and _iri(claim, RDF + "object") in operations
                    and self.index.pinned(claim)
                    and self.index.definition(symbol.id) is not None
                    and predicate not in responsibilities[symbol.id]
                ):
                    responsibilities[symbol.id].append(predicate)
        return operations, {
            key: value
            for key, value in responsibilities.items()
            if self.index.definition(key) is not None
        }

    def _contract(self, operations: dict[str, NodeRecord]) -> None:
        for operation_id in sorted(operations):
            for claim in self.index.claims("specifiedIn"):
                if _iri(claim, RDF + "subject") != operation_id:
                    continue
                contract = self.index.typed(_iri(claim, RDF + "object"), C1 + "Document")
                if contract is None or contract.id not in self.target.contracts:
                    continue
                for part in self.index.parts_of.get(contract.id, []):
                    self._part_unit(
                        "interface-contract",
                        "contract-part",
                        part,
                        contract,
                        (1, contract.id, _text(part, C1 + "orderKey") or "", part.id),
                        {claim.id},
                        specified_operations=sorted(
                            str(_iri(item, RDF + "subject"))
                            for item in self.index.claims("specifiedIn")
                            if _iri(item, RDF + "object") == contract.id
                            and _iri(item, RDF + "subject") in operations
                        ),
                    )
        if not any(unit["kind"] == "contract-part" for unit in self.units):
            self.gaps.append(
                {
                    "kind": "interface-contract",
                    "message": "No contract in the target that specifies the operations "
                    "is in the returned material.",
                }
            )

    # document structure and applicability ----------------------------------------

    def _inputs(self) -> dict[str, list[dict[str, Any]]]:
        """Readable applicability inputs per subject (Document or DocumentPart)."""
        targets = set(self.target.snapshots)
        inputs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for predicate, state in (
            ("describesSnapshot", "applicable"),
            ("notApplicableTo", "not-applicable"),
        ):
            for claim in self.index.claims(predicate):
                snapshot = _iri(claim, RDF + "object")
                if snapshot in targets:
                    inputs[str(_iri(claim, RDF + "subject"))].append(
                        {
                            "id": claim.id,
                            "kind": "declaration",
                            "predicate": predicate,
                            "snapshots": [snapshot],
                            "state": state,
                            "basis": "declared",
                            "attributed_to": _iri(claim, PROV + "wasAttributedTo"),
                            "review_state": _text(claim, C1 + "reviewState") or "reported",
                        }
                    )
        for record in self.records.values():
            if S + "ApplicabilityRecord" not in record.types:
                continue
            snapshots = sorted(set(_iris(record, S + "targetSnapshotRef")) & targets)
            subject = _iri(record, S + "subjectRef")
            if not snapshots or subject is None:
                continue
            inputs[subject].append(
                {
                    "id": record.id,
                    "kind": "record",
                    "snapshots": snapshots,
                    "state": _text(record, S + "applicabilityState"),
                    "basis": _text(record, S + "applicabilityBasis"),
                    "rule": _text(record, S + "ruleRef"),
                    "check": _iri(record, S + "checkRef"),
                    "review_state": _text(record, S + "reviewStatus") or "reported",
                    "note": _text(record, S + "recordNote"),
                }
            )
        for values in inputs.values():
            values.sort(key=lambda item: item["id"])
        return inputs

    @staticmethod
    def _effective(
        part_inputs: list[dict[str, Any]], document_inputs: list[dict[str, Any]], snapshot: str
    ) -> tuple[str, str | None]:
        for level, values in (("part", part_inputs), ("document", document_inputs)):
            states = [item["state"] for item in values if snapshot in item["snapshots"]]
            if states:
                return min(states, key=lambda state: CAUTION.get(state, 0)), level
        return "unknown", None

    def _structure(self, documented: set[str]) -> list[NodeRecord]:
        documented = documented | {self.anchor.id}
        candidates: set[str] = set()
        for claim in self.index.claims("documents"):
            if _iri(claim, RDF + "object") not in documented:
                continue
            subject = str(_iri(claim, RDF + "subject"))
            part = self.index.typed(subject, C1 + "DocumentPart")
            owner = _iri(part, C1 + "partOfDocument") if part is not None else subject
            if owner is not None and self.index.typed(owner, C1 + "Document") is not None:
                candidates.add(owner)
        inputs = self._inputs()
        selected: list[NodeRecord] = []
        for document_id in sorted(
            candidates, key=lambda item: (_label(self.records[item]) or "", item)
        ):
            document = self.records[document_id]
            parts = self.index.parts_of.get(document_id, [])
            if not inputs.get(document_id) and not any(inputs.get(part.id) for part in parts):
                self._other_target(document)
                continue
            selected.append(document)
            rank = len(selected)
            for part in parts:
                applicability = {}
                dependencies: set[str] = set()
                for snapshot in sorted(self.target.snapshots):
                    state, level = self._effective(
                        inputs.get(part.id, []), inputs.get(document_id, []), snapshot
                    )
                    contributing = [
                        {**item, "level": "part"}
                        for item in inputs.get(part.id, [])
                        if snapshot in item["snapshots"]
                    ] + [
                        {**item, "level": "document"}
                        for item in inputs.get(document_id, [])
                        if snapshot in item["snapshots"]
                    ]
                    dependencies.update(item["id"] for item in contributing)
                    applicability[snapshot] = {
                        "state": state,
                        "decided_at": level,
                        "records": contributing,
                    }
                self._part_unit(
                    "document-structure",
                    "document-part",
                    part,
                    document,
                    (rank, _text(part, C1 + "orderKey") or "", part.id),
                    dependencies,
                    document_title=_label(document),
                    issued=_text(document, DCT + "issued"),
                    applicability=applicability,
                    documents=sorted(
                        str(_iri(claim, RDF + "object"))
                        for claim in self.index.claims("documents")
                        if _iri(claim, RDF + "subject") == part.id
                        and _iri(claim, RDF + "object") in self.records
                    ),
                )
        return selected

    def _other_target(self, document: NodeRecord) -> None:
        self._add(
            {
                "id": _identifier("unit", "other", document.id),
                "section": "document-structure",
                "kind": "other-target-document",
                "role": self._role("other-target-document"),
                "statement": "no applicability declaration or record for the target; "
                "text not included",
                "document": {
                    "id": document.id,
                    "title": _label(document),
                    "issued": _text(document, DCT + "issued"),
                    "revision": _text(document, C1 + "sourceRevision"),
                },
                "citations": [],
                "_dependencies": [document.id],
            },
            (10_000, _label(document) or "", document.id),
        )

    # configuration and runs ------------------------------------------------------

    def _configuration(self) -> None:
        for configuration_id in sorted(self.target.configurations):
            configuration = self.records.get(configuration_id)
            if configuration is None:
                continue
            self._add(
                {
                    "id": _identifier("unit", "configuration", configuration_id),
                    "section": "configuration",
                    "kind": "configuration",
                    "role": self._role("configuration"),
                    "configuration": {
                        "id": configuration_id,
                        "name": _text(configuration, S + "configurationName"),
                        "parameters": sorted(
                            value.lexical
                            for value in configuration.properties.get(S + "parameter", [])
                            if not isinstance(value, str)
                        ),
                    },
                    "citations": [],
                    "_dependencies": [configuration_id],
                },
                (configuration_id,),
            )

    def _runs(self, operations: dict[str, NodeRecord]) -> None:
        cases = {
            str(_iri(claim, RDF + "subject"))
            for claim in self.index.claims("verifies")
            if _iri(claim, RDF + "object") in operations
            and self.index.typed(_iri(claim, RDF + "subject"), S + "TestCase") is not None
        }
        runs = [
            node
            for node in self.records.values()
            if S + "TestRun" in node.types and _iri(node, S + "testCaseRef") in cases
        ]
        runs.sort(key=lambda node: (_text(node, S + "startedAt") or "", node.id))
        for rank, run in enumerate(runs[: self.settings.max_runs]):
            view = self._run_view(run)
            dependencies = set(view.pop("_dependencies"))
            citations = view.pop("_citations")
            self._add(
                {
                    "id": _identifier("unit", "runs", run.id),
                    "section": "tests-and-runs",
                    "kind": "test-run",
                    "role": self._role("test-run"),
                    **view,
                    "citations": citations,
                    "_dependencies": sorted(dependencies),
                },
                (0 if view["match"] == "matching" else 1, rank, run.id),
            )

    # changes, drafts, compatibility ----------------------------------------------

    def _changes(self, documents: list[NodeRecord]) -> None:
        subjects = {document.id for document in documents} | {
            part.id for document in documents for part in self.index.parts_of.get(document.id, [])
        }
        targets = set(self.target.snapshots)
        for record in sorted(self.records.values(), key=lambda node: node.id):
            if (
                S + "ApplicabilityRecord" not in record.types
                or _iri(record, S + "subjectRef") not in subjects
                or _text(record, S + "applicabilityState") not in {"needs-review", "contradicted"}
                or not set(_iris(record, S + "targetSnapshotRef")) & targets
            ):
                continue
            dependencies = {record.id}
            citations = []
            for part_id in sorted(_iris(record, S + "evidencePartRef")):
                part = self.index.typed(part_id, C1 + "DocumentPart")
                document = (
                    self.index.typed(_iri(part, C1 + "partOfDocument"), C1 + "Document")
                    if part is not None
                    else None
                )
                if part is None or document is None:
                    continue
                dependencies.update((part.id, document.id))
                citations.append(self._part_citation(part, document))
            readable_digests = [
                value
                for value in (
                    getattr(item, "lexical", None)
                    for item in record.properties.get(S + "evidenceDigest", [])
                )
                if isinstance(value, str)
                and value.split("=", 1)[0] in {citation["part_id"] for citation in citations}
            ]
            self._add(
                {
                    "id": _identifier("unit", "changes", record.id),
                    "section": "changes",
                    "kind": "applicability-record",
                    "role": self._role("applicability-record"),
                    "record_id": record.id,
                    "subject": _iri(record, S + "subjectRef"),
                    "snapshots": sorted(set(_iris(record, S + "targetSnapshotRef")) & targets),
                    "state": _text(record, S + "applicabilityState"),
                    "basis": _text(record, S + "applicabilityBasis"),
                    "rule": _text(record, S + "ruleRef"),
                    "review_state": _text(record, S + "reviewStatus"),
                    "note": _text(record, S + "recordNote"),
                    "evidence_digests": sorted(readable_digests),
                    "statement": "a review candidate, not proof that the text is wrong"
                    if _text(record, S + "applicabilityState") == "needs-review"
                    else "an attributed finding with its evidence",
                    "citations": citations,
                    "_dependencies": sorted(dependencies),
                },
                (0, _iri(record, S + "subjectRef") or "", record.id),
            )
        # Recorded discrepancies touching a selected part (M09 D6 labels).
        self._discrepancies()

    def _drafts(self, documents: list[NodeRecord]) -> None:
        related = {document.id for document in documents} | {
            unit["document"]["id"] for unit in self.units if unit["kind"] == "other-target-document"
        }
        publications: dict[str, list[NodeRecord]] = defaultdict(list)
        for node in self.records.values():
            if S + "ExternalPublication" in node.types:
                draft_ref = _iri(node, S + "draftRef")
                if draft_ref is not None:
                    publications[draft_ref].append(node)
        lineage: dict[str, list[NodeRecord]] = defaultdict(list)
        for claim in self.index.assertions.get(PROV + "wasDerivedFrom", []):
            subject = _iri(claim, RDF + "subject")
            if subject is not None and _iri(claim, RDF + "object") in self.records:
                lineage[subject].append(claim)
        for draft in sorted(self.records.values(), key=lambda node: node.id):
            if S + "DocumentationDraft" not in draft.types:
                continue
            if _iri(draft, S + "revises") not in related:
                continue
            document = self.index.typed(_iri(draft, S + "documentRef"), C1 + "Document")
            if document is None:
                continue
            dependencies = {draft.id, document.id}
            parts: list[dict[str, Any]] = []
            for part in self.index.parts_of.get(document.id, []):
                dependencies.add(part.id)
                sources: list[dict[str, Any]] = []
                for claim in lineage.get(part.id, []):
                    source = self.records[str(_iri(claim, RDF + "object"))]
                    source_document = self.index.typed(
                        _iri(source, C1 + "partOfDocument"), C1 + "Document"
                    )
                    if source_document is None:
                        continue
                    dependencies.update((claim.id, source.id, source_document.id))
                    sources.append(
                        {
                            "assertion_id": claim.id,
                            "source_part": source.id,
                            "path": _text(source_document, DCT + "title"),
                            "revision": _text(source_document, C1 + "sourceRevision"),
                        }
                    )
                parts.append(
                    {
                        "part_id": part.id,
                        "text": _text(part, C1 + "text") or "",
                        "derived_from": sorted(sources, key=lambda item: item["source_part"]),
                    }
                )
            published = sorted(publications.get(draft.id, []), key=lambda node: node.id)
            dependencies.update(node.id for node in published)
            self._add(
                {
                    "id": _identifier("unit", "drafts", draft.id),
                    "section": "drafts",
                    "kind": "draft",
                    "role": self._role("draft"),
                    "draft_id": draft.id,
                    "title": _label(document),
                    "revises": _iri(draft, S + "revises"),
                    "draft_state": _text(draft, S + "draftState"),
                    "target_snapshots": sorted(_iris(draft, S + "targetSnapshotRef")),
                    "author": _iri(draft, S + "authorRef"),
                    "publication_state": "published" if published else "not-published",
                    "publications": [
                        {
                            "id": node.id,
                            "locator": sorted(
                                value.lexical
                                for value in node.properties.get(S + "locator", [])
                                if not isinstance(value, str)
                            ),
                            "published_at": _text(node, S + "publishedAt"),
                            "publisher": _iri(node, S + "publisherRef"),
                        }
                        for node in published
                    ],
                    "statement": "a C1 draft; C1 approval is not external publication",
                    "parts": parts,
                    "citations": [],
                    "_dependencies": sorted(dependencies),
                },
                (draft.id,),
            )

    def _compatibility(self) -> None:
        live = [
            node
            for node in self.records.values()
            if S + "TestRun" in node.types and _text(node, S + "integrationMode") == "live"
        ]
        for left, right in combinations(sorted(self.target.snapshots), 2):
            if _iri(self.target.snapshots[left], S + "repositoryRef") == _iri(
                self.target.snapshots[right], S + "repositoryRef"
            ):
                continue
            matching = [
                run
                for run in sorted(live, key=lambda node: node.id)
                if {left, right} <= set(_iris(run, S + "snapshotRef"))
                and set(_iris(run, S + "snapshotRef")) <= set(self.target.snapshots)
                and (
                    _iri(run, S + "configurationRef") in self.target.configurations
                    if self.target.configurations
                    else _iri(run, S + "configurationRef") is None
                )
            ]
            self._add(
                {
                    "id": _identifier("unit", "compatibility", left, right),
                    "section": "compatibility",
                    "kind": "compatibility",
                    "role": self._role("compatibility"),
                    "pair": [left, right],
                    "status": "observed" if matching else "unknown",
                    "runs": [
                        {"run_id": run.id, "result": _text(run, S + "result")} for run in matching
                    ],
                    "statement": "observed live run evidence for exactly this pair"
                    if matching
                    else COMPATIBILITY_UNKNOWN,
                    "citations": [],
                    "_dependencies": sorted({left, right, *(run.id for run in matching)}),
                },
                (left, right),
            )
