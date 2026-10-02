"""M11 D1–D8: effective applicability, the review rule, approval coverage, draft rules."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from c1.authorization.models import Operation, Scope
from c1.authorization.operations import SecurityOperations, _required_scopes
from c1.changes.drafts import draft_diagnostics
from c1.changes.models import CreateOperation, ReplaceOperation
from c1.context.doc_update import DocUpdateSelection
from c1.context.profiles import SoftwareContextProfile, load_any_context_profile
from c1.interchange import validate_records
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts import doc_review_rule as rule  # noqa: E402
from scripts import software_producer as sp  # noqa: E402

S = "urn:c1:ns:software#"
XSD = "http://www.w3.org/2001/XMLSchema#"
BASE = "urn:c1:instance:dev:"


def lit(value: str, datatype: str = "string") -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + datatype)


# D2: effective state ---------------------------------------------------------------


def _input(state: str, snapshots: list[str]) -> dict[str, Any]:
    return {"id": state + "/" + ",".join(snapshots), "state": state, "snapshots": snapshots}


@pytest.mark.parametrize(
    ("part", "document", "expected"),
    [
        ([], [], ("unknown", None)),
        ([], [_input("applicable", ["s"])], ("applicable", "document")),
        ([], [_input("applicable", ["other"])], ("unknown", None)),
        ([_input("needs-review", ["s"])], [_input("applicable", ["s"])], ("needs-review", "part")),
        # Part-level inputs win even when the document level is more cautious.
        ([_input("applicable", ["s"])], [_input("not-applicable", ["s"])], ("applicable", "part")),
        (
            [_input("needs-review", ["s"]), _input("contradicted", ["s"])],
            [],
            ("contradicted", "part"),
        ),
        (
            [_input("applicable", ["s"]), _input("not-applicable", ["s"])],
            [],
            ("not-applicable", "part"),
        ),
        (
            [_input("needs-review", ["other"])],
            [_input("applicable", ["s"])],
            ("applicable", "document"),
        ),
    ],
)
def test_effective_state_truth_table(
    part: list[dict[str, Any]], document: list[dict[str, Any]], expected: tuple[str, str | None]
) -> None:
    assert DocUpdateSelection._effective(part, document, "s") == expected


# D3: the external review rule --------------------------------------------------------


def _planner() -> sp.Planner:
    principals = {key: BASE + "agent/" + key for key in ("indexer", "analyzer", "ci", "reviewer")}
    planner = sp.Planner(sp.load_inputs(), principals)
    planner.runs()
    return planner


def test_rule_flags_only_parts_whose_dependencies_changed() -> None:
    planner = _planner()
    parts = dict(planner._parts[("a1", "docs/invoicing.md")])
    findings = rule.evaluate(planner, {"snapshots": ["a2", "b2"], "contract": "a2"})
    assert {finding.operation for finding in findings} == {"createInvoice"}
    assert [parts[finding.part].kind for finding in findings] == ["heading-2", "text"]
    assert all(finding.target == "a2" and finding.described == "a1" for finding in findings)
    # Same snapshot as described: nothing to compare.
    assert rule.evaluate(planner, {"snapshots": ["a1", "b1"], "contract": "a1"}) == []


def test_rule_run_never_contradicts_and_validates() -> None:
    planner = _planner()
    run = rule.rule_run(
        planner, {"snapshots": ["a2", "b2"], "contract": "a2"}, "2026-03-01T09:00:00Z"
    )
    states = [
        record["properties"][S + "applicabilityState"][0]["lexical"]
        for record in run.records
        if S + "ApplicabilityRecord" in record["types"]
    ]
    assert states == ["needs-review", "needs-review"]
    registry = ProfileRegistry()
    registry.load(ROOT / "profiles/available/software")
    records = [
        NodeRecord.model_validate({key: value for key, value in item.items() if key != "scope"})
        for item in run.records
    ]
    assert len(validate_records(records, registry).records) == len(records)
    again = rule.rule_run(
        planner, {"snapshots": ["a2", "b2"], "contract": "a2"}, "2026-03-01T09:00:00Z"
    )
    assert [item["id"] for item in again.records] == [item["id"] for item in run.records]


# D7: approval coverage over lineage scopes ------------------------------------------


def _rescope(approvals: list[str], lineage: list[str] | None) -> Operation:
    payload: dict[str, Any] = {"bindings": []}
    if lineage is not None:
        payload["lineage"] = {"scopes": lineage, "sources": [], "claims": [], "digest": "d"}
    return Operation(
        id="op",
        kind="rescope",
        actor="user:carol",
        target="urn:draft",
        from_scope="drafts",
        to_scope="docs",
        state="proposed",
        approvals=approvals,
        payload=payload,
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )


def _operations(
    admins: set[tuple[str, str]], retired: frozenset[str] = frozenset()
) -> SecurityOperations:
    async def scope(identifier: str) -> Scope:
        return Scope(
            id=identifier, label=identifier, state="retired" if identifier in retired else "active"
        )

    async def check(user: str, _relation: str, obj: str) -> bool:
        return (user, obj.removeprefix("scope:")) in admins

    operations = object.__new__(SecurityOperations)
    operations.settings = cast(Any, SimpleNamespace(independent_review=True))
    operations.plane = cast(Any, SimpleNamespace(current=SimpleNamespace(scope=scope)))
    operations.fga = cast(Any, SimpleNamespace(check=check))
    return operations


ADMINS = {
    ("user:frank", "docs"),
    ("user:erin", "ledger"),
    ("user:erin", "shop"),
    ("user:carol", "docs"),
    ("user:carol", "drafts"),
}


@pytest.mark.parametrize(
    ("approvals", "lineage", "retired", "covered"),
    [
        (["user:frank"], None, set(), True),  # no lineage: destination only (M03 rule)
        (["user:frank"], ["ledger", "shop"], set(), False),  # missing lineage approval
        (["user:erin"], ["ledger", "shop"], set(), False),  # missing destination approval
        (["user:frank", "user:erin"], ["ledger", "shop"], set(), True),
        (["user:carol", "user:erin"], ["ledger", "shop"], set(), False),  # proposer never counts
        (["user:frank", "user:erin"], ["ledger", "shop", "restricted"], set(), False),  # extra
        (["user:frank", "user:erin"], ["ledger", "shop"], {"shop"}, False),  # stale scope
    ],
)
def test_lineage_approval_coverage(
    approvals: list[str], lineage: list[str] | None, retired: set[str], covered: bool
) -> None:
    op = _rescope(approvals, lineage)
    assert _required_scopes(op) == sorted({"docs", *(lineage or [])})
    result = asyncio.run(_operations(ADMINS, frozenset(retired))._covered(op))
    assert (result >= set(_required_scopes(op))) is covered


# D5, D6, D8: draft rules ----------------------------------------------------------------

DRAFT = BASE + "record/draft"
DOCUMENT = BASE + "document/draft"
CHECK = BASE + "record/check-1"
LATER = BASE + "record/check-2"


def _draft(state: str, snapshots: list[str], check: str | None = CHECK) -> dict[str, Any]:
    properties: dict[str, Any] = {
        S + "documentRef": [DOCUMENT],
        S + "targetSnapshotRef": snapshots,
        S + "authorRef": [BASE + "agent/bob"],
        S + "draftState": [{"lexical": state, "datatype": XSD + "string"}],
    }
    if check is not None:
        properties[S + "applicabilityCheckRef"] = [check]
    return {"id": DRAFT, "types": [S + "DocumentationDraft"], "properties": properties}


def _check(identifier: str, snapshots: list[str], checked: str) -> NodeRecord:
    properties: dict[str, list[str | LiteralValue]] = {
        S + "ruleRef": [lit(rule.RULE)],
        S + "targetSnapshotRef": list(snapshots),
        S + "checkedAt": [lit(checked, "dateTimeStamp")],
    }
    return NodeRecord(id=identifier, types=[S + "ApplicabilityCheck"], properties=properties)


def _run(
    operations: list[Any], checks: list[NodeRecord], kinds: dict[str, str] | None = None
) -> list[str]:
    kinds = kinds or {"drafts": "drafting", "docs": "standard"}
    by_id = {check.id: check for check in checks}

    async def scope_kind(scope: str) -> str | None:
        return kinds.get(scope)

    async def binding_scope(identifier: str) -> str | None:
        return "drafts" if identifier == DOCUMENT else None

    async def reference(identifier: str) -> NodeRecord | None:
        return by_id.get(identifier)

    async def checks_for(_rule: str) -> list[NodeRecord]:
        return checks

    diagnostics = asyncio.run(
        draft_diagnostics(
            operations,
            scope_kind=scope_kind,
            binding_scope=binding_scope,
            reference=reference,
            checks_for=checks_for,
        )
    )
    return [item.code for item in diagnostics]


def test_draft_must_be_created_in_a_drafting_scope() -> None:
    draft = _draft("draft", ["s1"], check=None)
    assert _run([CreateOperation(record=draft, scope_id="drafts")], []) == []
    assert _run([CreateOperation(record=draft, scope_id="docs")], []) == ["C1-CS-051"]
    document = {"id": DOCUMENT, "types": ["urn:c1:ns:core#Document"], "properties": {}}
    assert _run(
        [
            CreateOperation(record=document, scope_id="docs"),
            CreateOperation(record=draft, scope_id="drafts"),
        ],
        [],
    ) == ["C1-CS-051"]


def test_approval_requires_the_latest_check_for_exactly_the_target() -> None:
    current = _check(CHECK, ["s1", "s2"], "2026-03-01T09:00:00Z")
    approve = ReplaceOperation(
        resource_id=DRAFT, record=_draft("approved", ["s1", "s2"]), reason="approve"
    )
    assert _run([approve], [current]) == []
    moved = ReplaceOperation(
        resource_id=DRAFT, record=_draft("approved", ["s1", "s3"]), reason="approve"
    )
    assert _run([moved], [current]) == ["C1-CS-050"]
    later = _check(LATER, ["s1", "s2"], "2026-03-02T09:00:00Z")
    assert _run([approve], [current, later]) == ["C1-CS-050"]
    unrelated = _check(LATER, ["s1"], "2026-03-02T09:00:00Z")
    assert _run([approve], [current, unrelated]) == []
    missing = ReplaceOperation(
        resource_id=DRAFT, record=_draft("approved", ["s1", "s2"], check=None), reason="approve"
    )
    assert _run([missing], [current]) == ["C1-CS-050"]


def test_publication_receipt_is_rejected_in_a_drafting_scope() -> None:
    receipt = {
        "id": BASE + "record/publication",
        "types": [S + "ExternalPublication"],
        "properties": {S + "draftRef": [DRAFT]},
    }
    assert _run([CreateOperation(record=receipt, scope_id="drafts")], []) == ["C1-CS-052"]
    assert _run([CreateOperation(record=receipt, scope_id="docs")], []) == []


# D4: closed profile grammar ---------------------------------------------------------------


def test_documentation_update_profile_grammar() -> None:
    profile = load_any_context_profile(ROOT / "profiles/context/documentation-update.json")
    assert isinstance(profile, SoftwareContextProfile)
    for field, value in (("requires_aspects", True), ("requires_goal", True)):
        data = profile.model_dump(mode="json")
        data["software"][field] = value
        with pytest.raises(ValueError):
            SoftwareContextProfile.model_validate(data)
    data = profile.model_dump(mode="json")
    data["software"]["sections"] = list(reversed(data["software"]["sections"]))
    with pytest.raises(ValueError):
        SoftwareContextProfile.model_validate(data)
    data = profile.model_dump(mode="json")
    del data["software"]["role_map"]["compatibility"]
    with pytest.raises(ValueError):
        SoftwareContextProfile.model_validate(data)
