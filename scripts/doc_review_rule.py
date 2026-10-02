"""External review-candidate rule `doc-dependency-change/1` (M11 D3, ADR-0022).

Runs outside C1, as the analyzer producer, over the same checked-in inputs
the producer imports. For a documentation part that declares `documents` for
an interface operation, it compares the part's described snapshot with each
target snapshot of the same repository:

* the operation's object in the contract at each snapshot (canonical digest);
* the definition part of the operation's declared handler (text digest).

If either differs, or one side is missing, the part becomes a review
candidate: an `ApplicabilityRecord` with state `needs-review` and basis `rule`,
citing the compared parts and their digests. The rule never submits
`contradicted` and never states that prose is false; C1 runs no analysis.
Every run also records one `ApplicabilityCheck` for its exact target, which a
draft approval must name (M11 D6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from scripts import software_producer as sp

RULE = "doc-dependency-change/1"


@dataclass(frozen=True)
class Finding:
    """One review candidate: a documented part relative to one target snapshot."""

    part: str
    path: str
    described: str
    target: str
    operation: str
    evidence: tuple[tuple[str, str], ...]  # (part id, digest or "missing")
    note: str


def _operation(contract: bytes, name: str) -> tuple[str | None, str | None]:
    """The canonical digest and declared handler of one operation, if present."""
    spec = json.loads(contract)
    for methods in spec.get("paths", {}).values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") == name:
                handler = operation.get("x-c1-handler")
                return sp.canonical_digest(operation), handler if isinstance(handler, str) else None
    return None, None


def _definition(
    planner: sp.Planner, snapshot: str, handler: str | None
) -> tuple[str | None, str | None]:
    if handler is None or "." not in handler:
        return None, None
    module, function = handler.rsplit(".", 1)
    part = planner._definition_part(
        snapshot, planner.repo_of(snapshot), f"`{module}`/{function}()."
    )
    if part is None:
        return None, None
    for stored in planner._parts.values():
        for identifier, value in stored:
            if identifier == part:
                return part, sp.sha256(value.text.encode())
    return part, None


def evaluate(planner: sp.Planner, target: dict[str, Any]) -> list[Finding]:
    """Deterministic review candidates for one target; the planner must have run."""
    fixture = planner.fixture
    contract = fixture["contracts"]
    findings: list[Finding] = []
    for path, documented in sorted(fixture.get("part_documents", {}).items()):
        spec = fixture["documentation"][path]
        for described in spec["describes"]:
            if path not in planner.inputs.files.get(described, {}):
                continue
            by_section = sp.section_parts(planner._parts[(described, path)])
            for snapshot in target["snapshots"]:
                if planner.repo_of(snapshot) != planner.repo_of(described) or snapshot == described:
                    continue
                for section, names in sorted(documented.items()):
                    for name in names:
                        before, handler_before = _operation(
                            planner.inputs.files[described][contract["path"]], name
                        )
                        after, handler_after = _operation(
                            planner.inputs.files[snapshot][contract["path"]], name
                        )
                        part_before, code_before = _definition(planner, described, handler_before)
                        part_after, code_after = _definition(planner, snapshot, handler_after)
                        changed = []
                        if before is None or before != after:
                            changed.append("contract operation " + name)
                        if code_before is None or code_before != code_after:
                            changed.append("handler " + str(handler_after or handler_before))
                        if not changed:
                            continue
                        evidence = [
                            (planner._parts[(described, contract["path"])][0][0], before),
                            (planner._parts[(snapshot, contract["path"])][0][0], after),
                        ]
                        evidence += [
                            (identifier, digest)
                            for identifier, digest in (
                                (part_before, code_before),
                                (part_after, code_after),
                            )
                            if identifier is not None
                        ]
                        for part in by_section.get(section, []):
                            findings.append(
                                Finding(
                                    part=part,
                                    path=path,
                                    described=described,
                                    target=snapshot,
                                    operation=name,
                                    evidence=tuple(
                                        (identifier, digest or "missing")
                                        for identifier, digest in evidence
                                    ),
                                    note="dependency changed between "
                                    + described
                                    + " and "
                                    + snapshot
                                    + ": "
                                    + "; ".join(changed),
                                )
                            )
    return findings


def check_id(target: dict[str, Any], checked_at: str) -> str:
    key = sp.canonical_digest({"rule": RULE, "target": target, "checked_at": checked_at})
    return sp.ident(f"applicability-check/{key}", "record")


def rule_run(planner: sp.Planner, target: dict[str, Any], checked_at: str) -> sp.Run:
    """The analyzer run that records one check and its review candidates."""
    principal = planner.principals["analyzer"]
    key = sp.canonical_digest({"target": target, "checked_at": checked_at})[:16]
    first = target["snapshots"][0]
    activity = sp.activity_record(f"rule/{key}", principal, "doc-review-rule", [], "sw-shared")
    run = sp.Run(f"rule/{key}", "analyzer", "doc-review-rule", first, activity)
    run.add(activity)
    findings = evaluate(planner, target)
    paths = sorted({finding.path for finding in findings}) or sorted(
        planner.fixture.get("part_documents", {})
    )
    documentation = planner.fixture["documentation"]
    scope = planner.file_scope(documentation[paths[0]]["describes"][0], paths[0])
    check = check_id(target, checked_at)
    contracts = [sp.file_id(target["contract"], planner.fixture["contracts"]["path"])]
    run.add(
        {
            "id": check,
            "types": [sp.S + "ApplicabilityCheck"],
            "scope": scope,
            "properties": {
                sp.S + "ruleRef": [sp.lit(RULE)],
                sp.S + "targetSnapshotRef": [sp.snapshot_id(item) for item in target["snapshots"]],
                sp.S + "targetContractRef": contracts,
                sp.S + "checkedAt": [sp.lit(checked_at, "dateTimeStamp")],
                sp.S + "activityRef": [activity["id"]],
            },
        }
    )
    for finding in findings:
        record_key = sp.canonical_digest(
            {"check": check, "part": finding.part, "target": finding.target}
        )
        run.add(
            {
                "id": sp.ident(f"applicability/{record_key}", "record"),
                "types": [sp.S + "ApplicabilityRecord"],
                "scope": planner.file_scope(finding.described, finding.path),
                "properties": {
                    sp.S + "subjectRef": [finding.part],
                    sp.S + "targetSnapshotRef": [sp.snapshot_id(finding.target)],
                    sp.S + "applicabilityState": [sp.lit("needs-review")],
                    sp.S + "applicabilityBasis": [sp.lit("rule")],
                    sp.S + "ruleRef": [sp.lit(RULE)],
                    sp.S + "checkRef": [check],
                    sp.S + "activityRef": [activity["id"]],
                    sp.S + "evidencePartRef": sorted({part for part, _ in finding.evidence}),
                    sp.S + "evidenceDigest": [
                        sp.lit(f"{part}={digest}") for part, digest in finding.evidence
                    ],
                    sp.S + "recordNote": [sp.lit(finding.note)],
                    sp.S + "reviewStatus": [sp.lit("reported")],
                },
            }
        )
    return run
