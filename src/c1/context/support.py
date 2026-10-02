"""Documentation-first support selection (M10 D2–D9) over authorized records only.

Two explicit stages share the M09 software selection helpers. The documentation
stage returns target-applicable guidance before any other documentation and
never lets a newer guide for another target replace it; declared
non-applicability and recorded discrepancies are warnings, never hidden. The
implementation stage returns only code, configuration, interfaces and runs
declared for the requested aspects. Neither stage judges sufficiency, and a
missing aspect is reported only as missing from the returned material.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from c1.context.errors import ContextError
from c1.context.profiles import TASK_TEMPLATES, SoftwareContextProfile
from c1.context.request import IDSelector, LabelSelector
from c1.context.resolve import candidate, label_matches
from c1.context.software import SoftwareSelection, _identifier, _label
from c1.model.nodes import NodeRecord
from c1.software.service import C1, DCT, RDF, S, Target, _iri, _text

GUIDANCE_LABEL = "official guidance"
IMPLEMENTATION_LABEL = "implementation evidence, not a supported procedure"
PUBLICATION_STATEMENT = (
    "Prepared for the requesting principal; read access is not publication permission."
)
MISSING_TEXT = "not addressed by the returned material"
_REVIEW_RANK = {"confirmed": 0, "reported": 1, "disputed": 2}


def resolve_aspects(
    records: dict[str, NodeRecord], requested: list[str | IDSelector]
) -> tuple[list[NodeRecord], list[dict[str, Any]]]:
    """Exact aspect resolution; hidden and unknown aspects answer alike."""
    aspects = {key: node for key, node in records.items() if S + "Aspect" in node.types}
    resolved: list[NodeRecord] = []
    report: list[dict[str, Any]] = []
    for item in requested:
        if isinstance(item, IDSelector):
            node = aspects.get(item.id)
            matches = [node] if node is not None else []
            shown = item.id
        else:
            selector = LabelSelector(label=item)
            matches = [node for _, node in sorted(aspects.items()) if label_matches(node, selector)]
            shown = item
        if len(matches) == 1:
            resolved.append(matches[0])
            report.append(
                {"requested": shown, "outcome": "resolved", "aspect": candidate(matches[0])}
            )
        else:
            report.append(
                {
                    "requested": shown,
                    "outcome": "ambiguous" if matches else "unresolved",
                    "candidates": [candidate(node) for node in matches],
                }
            )
    unique = list({node.id: node for node in resolved}.values())
    return unique, report


class SupportSelection(SoftwareSelection):
    def __init__(
        self,
        records: dict[str, NodeRecord],
        target: Target,
        anchor: NodeRecord,
        profile: SoftwareContextProfile,
        aspects: list[NodeRecord],
        *,
        deadline: float,
    ) -> None:
        super().__init__(records, target, anchor, profile, deadline=deadline)
        self.task = profile.software.task
        self.sections = TASK_TEMPLATES[self.task][0]
        self.aspects = aspects
        self.aspect_ids = {node.id for node in aspects}
        self.addressed: set[str] = set()

    def _add(self, unit: dict[str, Any], order: tuple[Any, ...]) -> None:
        if unit["id"] in self._unit_ids:
            return
        self._unit_ids.add(unit["id"])
        unit["_order"] = (self.sections.index(unit["section"]), *order)
        self.units.append(unit)

    def _aspect_claims(self, subject: str) -> list[NodeRecord]:
        return [
            claim
            for claim in self.index.claims("addressesAspect")
            if _iri(claim, RDF + "subject") == subject
            and _iri(claim, RDF + "object") in self.records
        ]

    def missing_aspects(self) -> list[dict[str, Any]]:
        return [
            {"aspect": candidate(node), "status": MISSING_TEXT}
            for node in self.aspects
            if node.id not in self.addressed
        ]

    def build(self) -> dict[str, Any]:
        if self.task == "support-documentation":
            self._documentation()
        else:
            self._support_implementation()
        self.units.sort(key=lambda unit: unit["_order"])
        for unit in self.units:
            del unit["_order"]
        return {"outcome": "resolved", "symbols": []}

    # documentation stage -----------------------------------------------------------

    def _documentation(self) -> None:
        anchors = {self.anchor.id}
        candidates: dict[str, set[str]] = defaultdict(set)
        for claim in self.index.claims("documents"):
            if _iri(claim, RDF + "object") in anchors:
                candidates[str(_iri(claim, RDF + "subject"))].add(claim.id)
        part_aspects: dict[str, list[NodeRecord]] = defaultdict(list)
        for claim in self.index.claims("addressesAspect"):
            subject = str(_iri(claim, RDF + "subject"))
            part = self.index.typed(subject, C1 + "DocumentPart")
            if part is not None and _iri(claim, RDF + "object") in self.records:
                part_aspects[part.id].append(claim)
                if _iri(claim, RDF + "object") in self.aspect_ids:
                    candidates[str(_iri(part, C1 + "partOfDocument"))].add(claim.id)
        describes: dict[str, list[NodeRecord]] = defaultdict(list)
        for claim in self.index.claims("describesSnapshot"):
            describes[str(_iri(claim, RDF + "subject"))].append(claim)
        not_applicable: dict[str, list[NodeRecord]] = defaultdict(list)
        for claim in self.index.claims("notApplicableTo"):
            if _iri(claim, RDF + "object") in self.target.snapshots:
                not_applicable[str(_iri(claim, RDF + "subject"))].append(claim)

        applicable: list[tuple[NodeRecord, list[NodeRecord]]] = []
        for document_id in sorted(candidates):
            document = self.index.typed(document_id, C1 + "Document")
            if document is None:
                continue
            own = [
                claim
                for claim in describes.get(document.id, [])
                if _iri(claim, RDF + "object") in self.target.snapshots
            ]
            warnings = not_applicable.get(document.id, [])
            if warnings:
                for claim in warnings:
                    self._applicability_warning(document, claim)
            elif own:
                applicable.append((document, own))
            elif any(
                _iri(claim, RDF + "object") in anchors
                for claim in self.index.claims("documents")
                if _iri(claim, RDF + "subject") == document.id
            ):
                self._other_target(document, describes.get(document.id, []))

        def rank(item: tuple[NodeRecord, list[NodeRecord]]) -> int:
            return min(
                _REVIEW_RANK.get(_text(claim, C1 + "reviewState") or "reported", 3)
                for claim in item[1]
            )

        # Applicability first; review state before recency; recency only breaks ties.
        applicable.sort(key=lambda item: item[0].id)
        applicable.sort(key=lambda item: _text(item[0], DCT + "issued") or "", reverse=True)
        applicable.sort(key=rank)
        for position, (document, claims) in enumerate(applicable):
            for part in self.index.parts_of.get(document.id, []):
                aspects = sorted(
                    str(_iri(claim, RDF + "object")) for claim in part_aspects.get(part.id, [])
                )
                self.addressed.update(aspects)
                self._part_unit(
                    "guidance",
                    "guidance-part",
                    part,
                    document,
                    (position, _text(part, C1 + "orderKey") or "", part.id),
                    {claim.id for claim in claims}
                    | {claim.id for claim in part_aspects.get(part.id, [])},
                    label=GUIDANCE_LABEL,
                    document_title=_label(document),
                    issued=_text(document, DCT + "issued"),
                    aspects=aspects,
                    applicability=[
                        {"snapshot": _iri(claim, RDF + "object"), "assertion_id": claim.id}
                        for claim in claims
                    ],
                )
        for claim in self.index.claims("discrepancy"):
            implementation_part = str(_iri(claim, RDF + "subject"))
            normative_part = str(_iri(claim, RDF + "object"))
            if (
                implementation_part not in self.selected_parts
                and normative_part not in self.selected_parts
            ):
                continue
            dependencies: set[str] = set()
            view = self._claim_view(claim, dependencies)
            self._add(
                {
                    "id": _identifier("unit", "warnings", claim.id),
                    "section": "warnings",
                    "kind": "discrepancy",
                    "role": self._role("discrepancy"),
                    **view,
                    "implementation_part": implementation_part,
                    "normative_part": normative_part,
                    "citations": self._evidence_citations(claim, dependencies),
                    "_dependencies": sorted(dependencies | {implementation_part, normative_part}),
                },
                (1, claim.id),
            )

    def _applicability_warning(self, document: NodeRecord, claim: NodeRecord) -> None:
        dependencies = {document.id}
        view = self._claim_view(claim, dependencies)
        snapshot = self.records.get(_iri(claim, RDF + "object") or "")
        self._add(
            {
                "id": _identifier("unit", "warnings", claim.id),
                "section": "warnings",
                "kind": "applicability-warning",
                "role": self._role("applicability-warning"),
                "statement": "declared not applicable to a target snapshot",
                "document": {
                    "id": document.id,
                    "title": _label(document),
                    "issued": _text(document, DCT + "issued"),
                },
                "snapshot": {"id": _iri(claim, RDF + "object"), "label": _label(snapshot)},
                **view,
                "citations": self._evidence_citations(claim, dependencies),
                "_dependencies": sorted(dependencies),
            },
            (0, _label(document) or "", claim.id),
        )

    def _other_target(self, document: NodeRecord, claims: list[NodeRecord]) -> None:
        described = []
        dependencies = {document.id}
        for claim in sorted(claims, key=lambda item: item.id):
            snapshot = self.records.get(_iri(claim, RDF + "object") or "")
            if snapshot is not None:
                dependencies.update((claim.id, snapshot.id))
                described.append({"id": snapshot.id, "label": _label(snapshot)})
        self._add(
            {
                "id": _identifier("unit", "other", document.id),
                "section": "other-target-documentation",
                "kind": "other-target-document",
                "role": self._role("other-target-document"),
                "statement": "not declared applicable to the target; text not included",
                "document": {
                    "id": document.id,
                    "title": _label(document),
                    "issued": _text(document, DCT + "issued"),
                },
                "describes": described,
                "citations": [],
                "_dependencies": sorted(dependencies),
            },
            (_text(document, DCT + "issued") or "", document.id),
        )

    # implementation stage ----------------------------------------------------------

    def _support_implementation(self) -> None:
        symbol_claims: dict[str, list[NodeRecord]] = defaultdict(list)
        for claim in self.index.claims("addressesAspect"):
            obj = _iri(claim, RDF + "object")
            symbol = self.index.typed(_iri(claim, RDF + "subject"), S + "CodeSymbol")
            if obj in self.aspect_ids and symbol is not None and self.index.pinned(claim):
                if self.index.definition(symbol.id) is not None:
                    symbol_claims[symbol.id].append(claim)
        symbols = sorted(
            (self.records[identifier] for identifier in symbol_claims),
            key=lambda node: (_label(node) or "", node.id),
        )
        for claims in symbol_claims.values():
            self.addressed.update(str(_iri(claim, RDF + "object")) for claim in claims)
        if symbols:
            self._implementation(symbols, {node.id for node in symbols})
        for unit in self.units:
            if unit["kind"] in {"code-unit", "dependency-unit"}:
                unit["label"] = IMPLEMENTATION_LABEL
        for identifier, claims in sorted(symbol_claims.items()):
            for claim in sorted(claims, key=lambda item: item.id):
                dependencies: set[str] = {identifier}
                view = self._claim_view(claim, dependencies)
                self._add(
                    {
                        "id": _identifier("unit", "interpretations", claim.id),
                        "section": "interpretations",
                        "kind": "aspect-claim",
                        "role": self._role("aspect-claim"),
                        "symbol": {"id": identifier, "label": _label(self.records[identifier])},
                        "aspect": candidate(self.records[str(_iri(claim, RDF + "object"))]),
                        **view,
                        "citations": self._evidence_citations(claim, dependencies),
                        "_dependencies": sorted(dependencies),
                    },
                    (identifier, claim.id),
                )
        for configuration_id in sorted(self.target.configurations):
            configuration = self.records.get(configuration_id)
            if configuration is None:
                continue
            claims = [
                claim
                for claim in self._aspect_claims(configuration_id)
                if _iri(claim, RDF + "object") in self.aspect_ids
            ]
            if not claims:
                continue
            self.addressed.update(str(_iri(claim, RDF + "object")) for claim in claims)
            dependencies = {configuration_id} | {claim.id for claim in claims}
            self._add(
                {
                    "id": _identifier("unit", "configuration", configuration_id),
                    "section": "configuration",
                    "kind": "configuration",
                    "role": self._role("configuration"),
                    "label": IMPLEMENTATION_LABEL,
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
                    "_dependencies": sorted(dependencies),
                },
                (configuration_id,),
            )
        self._support_interfaces_and_runs({node.id for node in symbols})

    def _support_interfaces_and_runs(self, symbol_ids: set[str]) -> None:
        operations: dict[str, list[NodeRecord]] = defaultdict(list)
        for predicate in ("implementsOperation", "declaredCall"):
            for claim in self.index.claims(predicate):
                if _iri(claim, RDF + "subject") in symbol_ids and self.index.pinned(claim):
                    operation = self.index.typed(
                        _iri(claim, RDF + "object"), S + "InterfaceOperation"
                    )
                    if operation is not None:
                        operations[operation.id].append(claim)
        for operation_id, claims in sorted(operations.items()):
            operation = self.records[operation_id]
            dependencies = {operation_id}
            self._add(
                {
                    "id": _identifier("unit", "interfaces", operation_id),
                    "section": "interfaces",
                    "kind": "operation",
                    "role": self._role("operation"),
                    "operation": {
                        "id": operation_id,
                        "operation_id": _text(operation, S + "operationId"),
                        "http_method": _text(operation, S + "httpMethod"),
                        "path_template": _text(operation, S + "pathTemplate"),
                    },
                    "basis": [self._claim_view(claim, dependencies) for claim in claims],
                    "citations": [
                        citation
                        for claim in claims
                        for citation in self._evidence_citations(claim, dependencies)
                    ],
                    "_dependencies": sorted(dependencies),
                },
                (_text(operation, S + "operationId") or "", operation_id),
            )
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
                    "id": _identifier("unit", "observed", run.id),
                    "section": "observed-tests",
                    "kind": "test-run",
                    "role": self._role("test-run"),
                    **view,
                    "citations": citations,
                    "_dependencies": sorted(dependencies),
                },
                (0 if view["match"] == "matching" else 1, rank, run.id),
            )


def require_known_task(profile: SoftwareContextProfile) -> None:
    if profile.software.task not in TASK_TEMPLATES:
        raise ContextError(400, "C1-CX-002", "unknown_context_profile")
