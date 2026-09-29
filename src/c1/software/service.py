"""Target resolution and target-pinned lookup for the software profile (M08 D5, D9).

Both operations run over one authorized selection (M05): only readable records
with readable required references are visible, so matches, counts, ordering,
citations, and coverage never depend on hidden content. A target never means
"latest": snapshots are explicit, and a branch resolves only at an explicit
instant, with the resolution reported. The profile stays optional; while it is
not installed the routes answer as an unknown route.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.query.cursor import CursorError
from c1.query.plan import AuthorizedPlan, QueryPlanError

if TYPE_CHECKING:
    from c1.authorization.principal import Principal
    from c1.runtime import Runtime

S = "urn:c1:ns:software#"
C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
PROV = "http://www.w3.org/ns/prov#"
SKOS = "http://www.w3.org/2004/02/skos/core#"

KINDS = (
    "occurrences",
    "operations",
    "tests",
    "runs",
    "documents",
    "relationships",
    "coverage",
    "issues",
    "unresolved",
)

# The evidence basis of each relationship predicate (M08 D6).
BASIS = {
    S + "staticCall": "static-extraction",
    S + "declaredCall": "declared",
    S + "implementsOperation": "declared",
    S + "specifiedIn": "declared",
    S + "documents": "declared",
    S + "describesSnapshot": "declared",
    S + "releasedAs": "declared",
    S + "releaseOf": "declared",
    S + "repositoryOf": "declared",
    S + "definedAt": "structural",
    S + "verifies": "declared",
    S + "implementsCapability": "interpretive",
    S + "interpretedCall": "interpretive",
    S + "exercised": "observed",
    DCT + "source": "declared",
}
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")


def _iri(node: NodeRecord, predicate: str) -> str | None:
    values = node.properties.get(predicate, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def _iris(node: NodeRecord, predicate: str) -> list[str]:
    return [value for value in node.properties.get(predicate, []) if isinstance(value, str)]


def _text(node: NodeRecord, predicate: str) -> str | None:
    values = node.properties.get(predicate, [])
    return values[0].lexical if len(values) == 1 and isinstance(values[0], LiteralValue) else None


def _texts(node: NodeRecord, predicate: str) -> list[str]:
    return [
        value.lexical
        for value in node.properties.get(predicate, [])
        if isinstance(value, LiteralValue)
    ]


def _int(node: NodeRecord, predicate: str) -> int:
    value = _text(node, predicate)
    return int(value) if value is not None else 0


def _instant(value: str) -> datetime:
    if not _TIMESTAMP.fullmatch(value):
        raise QueryPlanError(400, "C1-SW-001", "invalid_timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class Target:
    snapshots: dict[str, NodeRecord]  # snapshot ID -> record, one per repository
    contracts: list[str] = field(default_factory=list)
    configurations: list[str] = field(default_factory=list)
    branch_resolutions: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    @property
    def commits(self) -> dict[str, str]:
        return {
            str(_text(record, S + "commitId")): identifier
            for identifier, record in self.snapshots.items()
        }

    def describe(self) -> dict[str, Any]:
        return {
            "snapshots": [
                {
                    "id": identifier,
                    "repository": _iri(record, S + "repositoryRef"),
                    "commit": _text(record, S + "commitId"),
                    "label": _text(record, SKOS + "prefLabel"),
                }
                for identifier, record in sorted(self.snapshots.items())
            ],
            "contracts": sorted(self.contracts),
            "configurations": sorted(self.configurations),
        }


class SoftwareService:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def _require_profile(self) -> None:
        if "software" not in self.runtime.registry.profiles:
            raise QueryPlanError(404, "C1-SW-404", "not_found")

    async def _selection(
        self, principal: Principal, revision: str | None
    ) -> tuple[AuthorizedPlan, dict[str, NodeRecord], str, float]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        if revision is None:
            head, (plan, _) = await asyncio.gather(
                self.runtime.knowledge.head(),
                self.runtime.query.selection(principal, deadline=deadline),
            )
            selected = head
        else:
            selected = revision
            plan, _ = await self.runtime.query.selection(principal, deadline=deadline)
        records = await self.runtime.query.records(plan, selected, deadline=deadline)
        return plan, dict(records.items()), selected, deadline

    async def _finish(self, principal: Principal, plan: AuthorizedPlan, deadline: float) -> None:
        await self.runtime.query.planner.finalize(principal, plan, deadline=deadline)

    # targets ---------------------------------------------------------------------------

    def _typed(self, records: dict[str, NodeRecord], identifier: str, cls: str) -> NodeRecord:
        record = records.get(identifier)
        if record is None or cls not in record.types:
            # Hidden, missing, and wrong-class members answer identically.
            raise QueryPlanError(404, "C1-SW-404", "not_found")
        return record

    def resolve_target(self, records: dict[str, NodeRecord], spec: dict[str, Any]) -> Target:
        if not isinstance(spec, dict):
            raise QueryPlanError(400, "C1-SW-001", "invalid_target")
        allowed = {"target_set_id", "snapshots", "branches", "as_of", "contracts", "configurations"}
        if set(spec) - allowed:
            raise QueryPlanError(400, "C1-SW-001", "invalid_target")
        snapshot_ids: list[str] = []
        contracts: list[str] = []
        configurations: list[str] = []
        if "target_set_id" in spec:
            if set(spec) != {"target_set_id"}:
                raise QueryPlanError(400, "C1-SW-001", "invalid_target")
            target_set = self._typed(records, str(spec["target_set_id"]), S + "TargetSet")
            snapshot_ids = _iris(target_set, S + "memberSnapshot")
            contracts = _iris(target_set, S + "memberContract")
            configurations = _iris(target_set, S + "memberConfiguration")
        else:
            snapshot_ids = self._list(spec.get("snapshots", []))
            contracts = self._list(spec.get("contracts", []))
            configurations = self._list(spec.get("configurations", []))
        branches = spec.get("branches", [])
        if not isinstance(branches, list) or len(branches) > 50:
            raise QueryPlanError(400, "C1-SW-001", "invalid_target")
        if not snapshot_ids and not branches:
            # There is no implicit "latest" target (spec §10.2).
            raise QueryPlanError(400, "C1-SW-002", "target_required")
        if branches and "as_of" not in spec:
            raise QueryPlanError(400, "C1-SW-003", "as_of_required")
        target = Target({})
        for identifier in snapshot_ids:
            target.snapshots[identifier] = self._typed(records, identifier, S + "SourceSnapshot")
        if branches:
            instant = _instant(str(spec["as_of"]))
            for branch in branches:
                if not isinstance(branch, dict) or set(branch) != {"repository", "branch"}:
                    raise QueryPlanError(400, "C1-SW-001", "invalid_target")
                repository = self._typed(records, str(branch["repository"]), S + "CodeRepository")
                observations = [
                    record
                    for record in records.values()
                    if S + "BranchObservation" in record.types
                    and _iri(record, S + "repositoryRef") == repository.id
                    and _text(record, S + "branchName") == branch["branch"]
                    and _instant(str(_text(record, S + "branchObservedAt"))) <= instant
                    and _iri(record, S + "snapshotRef") in records
                ]
                if not observations:
                    target.unresolved.append(
                        {
                            "repository": repository.id,
                            "branch": branch["branch"],
                            "reason": "no-observation",
                        }
                    )
                    continue
                latest = max(
                    observations,
                    key=lambda item: (
                        _instant(str(_text(item, S + "branchObservedAt"))),
                        item.id,
                    ),
                )
                snapshot = str(_iri(latest, S + "snapshotRef"))
                target.snapshots[snapshot] = self._typed(records, snapshot, S + "SourceSnapshot")
                target.branch_resolutions.append(
                    {
                        "repository": repository.id,
                        "branch": branch["branch"],
                        "as_of": spec["as_of"],
                        "observation": latest.id,
                        "observed_at": _text(latest, S + "branchObservedAt"),
                        "snapshot": snapshot,
                    }
                )
        repositories = [_iri(record, S + "repositoryRef") for record in target.snapshots.values()]
        if len(repositories) != len(set(repositories)):
            raise QueryPlanError(400, "C1-SW-004", "one_snapshot_per_repository")
        for identifier in contracts:
            self._typed(records, identifier, C1 + "Document")
        for identifier in configurations:
            self._typed(records, identifier, S + "Configuration")
        target.contracts = contracts
        target.configurations = configurations
        return target

    @staticmethod
    def _list(value: Any) -> list[str]:
        if (
            not isinstance(value, list)
            or len(value) > 50
            or not all(isinstance(item, str) for item in value)
        ):
            raise QueryPlanError(400, "C1-SW-001", "invalid_target")
        return list(dict.fromkeys(value))

    async def resolve(
        self, principal: Principal, spec: dict[str, Any], revision: str | None = None
    ) -> dict[str, Any]:
        self._require_profile()
        plan, records, selected, deadline = await self._selection(principal, revision)
        target = self.resolve_target(records, spec)
        result = {
            "revision": selected,
            "target": target.describe(),
            "branch_resolutions": target.branch_resolutions,
            "unresolved": target.unresolved,
        }
        await self._finish(principal, plan, deadline)
        return result

    # lookup ----------------------------------------------------------------------------

    async def lookup(
        self,
        principal: Principal,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_profile()
        allowed = {"target", "select", "kinds", "limit", "cursor", "revision"}
        if not isinstance(body, dict) or set(body) - allowed or "target" not in body:
            raise QueryPlanError(400, "C1-SW-001", "invalid_request")
        kinds = body.get("kinds", list(KINDS))
        if not isinstance(kinds, list) or not kinds or set(kinds) - set(KINDS):
            raise QueryPlanError(400, "C1-SW-001", "invalid_kinds")
        limit = body.get("limit", 50)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise QueryPlanError(422, "C1-SW-005", "invalid_limit")
        select = body.get("select", {})
        allowed_select = {"symbol_id", "capability_id", "operation_id", "path_prefix"}
        if not isinstance(select, dict) or set(select) - allowed_select:
            raise QueryPlanError(400, "C1-SW-001", "invalid_select")
        digest = _digest({"target": body["target"], "select": select, "kinds": sorted(kinds)})
        cursor = body.get("cursor")
        revision = body.get("revision")
        after: tuple[str, str] | None = None
        if cursor:
            try:
                position = self.runtime.query.codec.decode(
                    str(cursor),
                    principal=principal.id,
                    filter_digest=digest,
                    order="software-lookup",
                    revision=revision,
                )
            except CursorError as exc:
                raise QueryPlanError(400, "C1-SW-006", "invalid_cursor") from exc
            revision, after = position.revision, position.last_key
        plan, records, selected, deadline = await self._selection(principal, revision)
        target = self.resolve_target(records, body["target"])
        items = self._items(records, target, select, set(kinds))
        items.sort(key=lambda item: (item["_order"], item["id"]))
        total = len(items)
        if after is not None:
            items = [item for item in items if (item["_order"], item["id"]) > after]
        page = items[:limit]
        next_cursor = (
            self.runtime.query.codec.encode(
                principal=principal.id,
                revision=selected,
                filter_digest=digest,
                order="software-lookup",
                last_key=(page[-1]["_order"], page[-1]["id"]),
            )
            if page and len(items) > limit
            else None
        )
        for item in page:
            del item["_order"]
        result = {
            "revision": selected,
            "target": target.describe(),
            "branch_resolutions": target.branch_resolutions,
            "unresolved_target": target.unresolved,
            "count": total,
            "items": page,
            "next_cursor": next_cursor,
        }
        await self._finish(principal, plan, deadline)
        return result

    def _items(
        self,
        records: dict[str, NodeRecord],
        target: Target,
        select: dict[str, Any],
        kinds: set[str],
    ) -> list[dict[str, Any]]:
        commits = target.commits
        order = {
            identifier: f"{index:03d}" for index, identifier in enumerate(sorted(target.snapshots))
        }
        assertions = [
            record
            for record in records.values()
            if C1 + "Assertion" in record.types and _iri(record, RDF + "predicate") in BASIS
        ]

        def related(predicate: str, obj: str) -> set[str]:
            return {
                str(_iri(item, RDF + "subject"))
                for item in assertions
                if _iri(item, RDF + "predicate") == predicate and _iri(item, RDF + "object") == obj
            }

        symbols: set[str] | None = None
        if "symbol_id" in select:
            symbols = {str(select["symbol_id"])}
        if "capability_id" in select:
            chosen = related(S + "implementsCapability", str(select["capability_id"]))
            symbols = chosen if symbols is None else symbols & chosen
        if "operation_id" in select:
            chosen = related(S + "implementsOperation", str(select["operation_id"])) | related(
                S + "declaredCall", str(select["operation_id"])
            )
            symbols = chosen if symbols is None else symbols & chosen
        prefix = select.get("path_prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise QueryPlanError(400, "C1-SW-001", "invalid_select")

        def in_target_document(identifier: str | None) -> NodeRecord | None:
            document = records.get(identifier) if identifier else None
            if document is None or C1 + "Document" not in document.types:
                return None
            if _text(document, C1 + "sourceRevision") not in commits:
                return None
            if prefix is not None and not str(_text(document, DCT + "title")).startswith(prefix):
                return None
            return document

        def citation(document: NodeRecord, part_id: str | None) -> dict[str, Any]:
            value: dict[str, Any] = {
                "document_id": document.id,
                "path": _text(document, DCT + "title"),
                "commit": _text(document, C1 + "sourceRevision"),
                "content_digest": _text(document, C1 + "contentDigest"),
            }
            part = records.get(part_id) if part_id else None
            if part is not None and _iri(part, C1 + "partOfDocument") == document.id:
                kind = _text(part, C1 + "partKind") or "text"
                value.update(
                    {
                        "part_id": part.id,
                        "part_kind": kind,
                        "code_completeness": "complete-unit"
                        if kind.startswith("code-unit")
                        else ("excerpt" if kind.startswith("code") else None),
                        "excerpt": _text(part, C1 + "text"),
                    }
                )
            return value

        items: list[dict[str, Any]] = []
        occurrence_ids: set[str] = set()
        selected_symbols: set[str] = set()
        for record in records.values():
            if S + "SymbolOccurrence" not in record.types:
                continue
            snapshot = _iri(record, S + "snapshotRef")
            if snapshot not in target.snapshots:
                continue
            symbol = str(_iri(record, S + "symbolRef"))
            if symbols is not None and symbol not in symbols:
                continue
            document = in_target_document(_iri(record, S + "fileRef"))
            if document is None:
                continue
            occurrence_ids.add(record.id)
            selected_symbols.add(symbol)
            if "occurrences" in kinds:
                symbol_record = records.get(symbol)
                items.append(
                    {
                        "_order": "1-{}-{}-{:06d}".format(
                            order[str(snapshot)],
                            _text(document, DCT + "title"),
                            _int(record, S + "startLine"),
                        ),
                        "kind": "occurrence",
                        "id": record.id,
                        "target_member": snapshot,
                        "basis": "structural",
                        "symbol": {
                            "id": symbol,
                            "label": _text(symbol_record, SKOS + "prefLabel")
                            if symbol_record
                            else None,
                            "descriptors": _text(symbol_record, S + "descriptors")
                            if symbol_record
                            else None,
                        },
                        "roles": sorted(_texts(record, S + "role")),
                        "range": {
                            "start_line": _int(record, S + "startLine"),
                            "start_character": _int(record, S + "startCharacter"),
                            "end_line": _int(record, S + "endLine"),
                            "end_character": _int(record, S + "endCharacter"),
                            "position_encoding": _text(record, S + "positionEncoding"),
                        },
                        "citation": citation(document, _iri(record, S + "partRef")),
                    }
                )

        def evidence_in_target(claim: NodeRecord) -> dict[str, Any] | None:
            for evidence_id in _iris(claim, C1 + "evidence"):
                evidence = records.get(evidence_id)
                if evidence is None:
                    continue
                revision = _text(evidence, C1 + "sourceRevision")
                source = _iri(evidence, OA + "hasSource")
                part = records.get(source) if source else None
                document = (
                    records.get(str(_iri(part, C1 + "partOfDocument")))
                    if part is not None and C1 + "DocumentPart" in part.types
                    else None
                )
                if revision in commits:
                    return {
                        "id": evidence.id,
                        "revision": revision,
                        "target_member": commits[str(revision)],
                        "citation": citation(document, part.id) if document and part else None,
                    }
                if revision and revision.startswith("report:") and document is not None:
                    return {
                        "id": evidence.id,
                        "revision": revision,
                        "target_member": None,
                        "citation": citation_report(document, part),
                    }
            return None

        def citation_report(document: NodeRecord, part: NodeRecord | None) -> dict[str, Any]:
            return {
                "document_id": document.id,
                "path": _text(document, DCT + "title"),
                "revision": _text(document, C1 + "sourceRevision"),
                "part_id": part.id if part is not None else None,
            }

        runs: dict[str, NodeRecord] = {}
        for record in records.values():
            if S + "TestRun" not in record.types:
                continue
            run_snapshots = _iris(record, S + "snapshotRef")
            if not run_snapshots or not set(run_snapshots) <= set(target.snapshots):
                continue
            configuration = _iri(record, S + "configurationRef")
            if target.configurations and configuration not in target.configurations:
                continue
            runs[record.id] = record
        run_cases = {str(_iri(record, S + "testCaseRef")) for record in runs.values()}

        target_occurrences = {
            record.id
            for record in records.values()
            if S + "SymbolOccurrence" in record.types
            and _iri(record, S + "snapshotRef") in target.snapshots
        }
        test_cases: dict[str, set[str]] = {}
        for claim in assertions:
            if (
                _iri(claim, RDF + "predicate") == S + "definedAt"
                and _iri(claim, RDF + "object") in target_occurrences
            ):
                test_cases.setdefault(str(_iri(claim, RDF + "subject")), set()).add(
                    str(_iri(claim, RDF + "object"))
                )

        relevant = selected_symbols | occurrence_ids | set(runs) | set(test_cases)
        operations: set[str] = set()
        for claim in assertions:
            predicate = str(_iri(claim, RDF + "predicate"))
            subject = str(_iri(claim, RDF + "subject"))
            obj = str(_iri(claim, RDF + "object"))
            evidence = evidence_in_target(claim)
            if evidence is None:
                continue
            if predicate == S + "specifiedIn" and (not target.contracts or obj in target.contracts):
                operations.add(subject)
            if symbols is not None and not ({subject, obj} & relevant):
                continue
            if prefix is not None and not ({subject, obj} & relevant):
                continue
            if "relationships" in kinds:
                items.append(
                    {
                        "_order": f"5-{predicate}-{subject}",
                        "kind": "relationship",
                        "id": claim.id,
                        "target_member": evidence["target_member"],
                        "basis": BASIS[predicate],
                        "predicate": predicate,
                        "subject": subject,
                        "object": obj,
                        "origin": _text(claim, C1 + "origin"),
                        "attributed_to": _iri(claim, PROV + "wasAttributedTo"),
                        "generated_by": _iri(claim, PROV + "wasGeneratedBy"),
                        "evidence": evidence,
                    }
                )

        if "operations" in kinds:
            for identifier in sorted(operations):
                operation = records.get(identifier)
                if operation is None or S + "InterfaceOperation" not in operation.types:
                    continue
                linked = related(S + "implementsOperation", identifier) | related(
                    S + "declaredCall", identifier
                )
                if (
                    symbols is not None
                    and identifier != select.get("operation_id")
                    and not linked & symbols
                ):
                    continue
                items.append(
                    {
                        "_order": f"2-{_text(operation, S + 'operationId')}",
                        "kind": "operation",
                        "id": identifier,
                        "target_member": None,
                        "basis": "declared",
                        "operation_id": _text(operation, S + "operationId"),
                        "http_method": _text(operation, S + "httpMethod"),
                        "path_template": _text(operation, S + "pathTemplate"),
                        "provider": _iri(operation, S + "providerRef"),
                    }
                )
        if "tests" in kinds:
            for identifier, occurrences in sorted(test_cases.items()):
                case = records.get(identifier)
                if case is None:
                    continue
                items.append(
                    {
                        "_order": f"3-{_text(case, SKOS + 'prefLabel')}",
                        "kind": "test",
                        "id": identifier,
                        "target_member": None,
                        "basis": "structural",
                        "label": _text(case, SKOS + "prefLabel"),
                        "definitions": sorted(occurrences),
                        "status": "has-matching-run"
                        if identifier in run_cases
                        else "definition-only",
                    }
                )
        if "runs" in kinds:
            for identifier, record in sorted(runs.items()):
                items.append(
                    {
                        "_order": f"4-{identifier}",
                        "kind": "run",
                        "id": identifier,
                        "target_member": sorted(_iris(record, S + "snapshotRef")),
                        "basis": "observed",
                        "test_case": _iri(record, S + "testCaseRef"),
                        "result": _text(record, S + "result"),
                        "integration_mode": _text(record, S + "integrationMode"),
                        "mocked_products": sorted(_iris(record, S + "mockedProductRef")),
                        "configuration": _iri(record, S + "configurationRef"),
                        "report": _iri(record, S + "reportRef"),
                    }
                )
        if "documents" in kinds:
            for claim in assertions:
                if _iri(claim, RDF + "predicate") != S + "describesSnapshot":
                    continue
                if _iri(claim, RDF + "object") not in target.snapshots:
                    continue
                document = records.get(str(_iri(claim, RDF + "subject")))
                if document is None:
                    continue
                if prefix is not None and not str(_text(document, DCT + "title")).startswith(
                    prefix
                ):
                    continue
                items.append(
                    {
                        "_order": "6-{}-{}".format(
                            _text(document, DCT + "title"), _iri(claim, RDF + "object")
                        ),
                        "kind": "document",
                        "id": document.id,
                        "target_member": _iri(claim, RDF + "object"),
                        "basis": "declared",
                        "path": _text(document, DCT + "title"),
                        "commit": _text(document, C1 + "sourceRevision"),
                        "describes": claim.id,
                    }
                )
        for kind, cls in (
            ("coverage", S + "ImportCoverage"),
            ("issues", S + "ImportIssue"),
            ("unresolved", S + "UnresolvedReference"),
        ):
            if kind not in kinds:
                continue
            for record in records.values():
                if cls not in record.types:
                    continue
                snapshot = _iri(record, S + "snapshotRef")
                if snapshot not in target.snapshots:
                    continue
                entry: dict[str, Any] = {
                    "_order": f"7-{kind}-{order[str(snapshot)]}",
                    "kind": kind.rstrip("s") if kind != "coverage" else "coverage",
                    "id": record.id,
                    "target_member": snapshot,
                    "activity": _iri(record, S + "activityRef"),
                }
                if kind == "coverage":
                    entry.update(
                        {
                            "method": _text(record, S + "importMethod"),
                            "state": _text(record, S + "coverageState"),
                            "analyzed": sorted(_texts(record, S + "analyzedScope")),
                            "payload_digest": _text(record, S + "payloadDigest"),
                        }
                    )
                elif kind == "issues":
                    file = records.get(str(_iri(record, S + "fileRef")))
                    entry.update(
                        {
                            "severity": _text(record, S + "severity"),
                            "code": _text(record, S + "issueCode"),
                            "message": _text(record, S + "issueMessage"),
                            "path": _text(file, DCT + "title") if file else None,
                        }
                    )
                else:
                    file = records.get(str(_iri(record, S + "fileRef")))
                    entry.update(
                        {
                            "symbol_text": _text(record, S + "symbolText"),
                            "reason": _text(record, S + "unresolvedReason"),
                            "path": _text(file, DCT + "title") if file else None,
                            "start_line": _int(record, S + "startLine"),
                        }
                    )
                items.append(entry)
        return items
