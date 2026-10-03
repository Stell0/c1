"""M11 real-service helpers: documentation-update requests, drafts and widening."""

from __future__ import annotations

import hashlib
import os
from typing import Any, cast
from urllib.parse import quote

import pytest

from scripts import doc_review_rule as rule
from scripts import software_producer as sp
from tests.integration.m03.conftest import LiveCase
from tests.integration.m10.conftest import context, section
from tests.integration.software import CaseLoader, Template

__all__ = ["context", "section"]

C1, S, RDF, PROV, DCT = sp.C1, sp.S, sp.RDF, sp.PROV, sp.DCT
MAXIMUM = 524288
CAPABILITY = sp.capability_id("invoice-creation")
INVOICING = ("a1", "docs/invoicing.md")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m11/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if os.environ.get("C1_STACK") != "1":
                item.add_marker(pytest.mark.skip(reason="M11 real services require C1_STACK=1"))


def target(*snapshots: str, contract: str = "a2") -> dict[str, Any]:
    return {
        "snapshots": [sp.snapshot_id(key) for key in snapshots],
        "contracts": [sp.file_id(contract, "openapi.json")],
        "configurations": [sp.configuration_id("default")],
    }


def update(spec: dict[str, Any], *, revision: str | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "profile": "documentation-update",
        "profile_version": "1",
        "anchor": {"id": CAPABILITY},
        "target": spec,
        "budget": {"unit": "bytes", "maximum": MAXIMUM},
        **extra,
    }
    if revision is not None:
        body["revision"] = revision
    return body


def units(value: dict[str, Any], name: str, kind: str | None = None) -> list[dict[str, Any]]:
    return [unit for unit in section(value, name) if kind is None or unit["kind"] == kind]


def parts_of(planner: sp.Planner, snapshot: str, path: str) -> dict[str, str]:
    """Part ID -> section name ("" before the first heading-2)."""
    by_section = sp.section_parts(planner._parts[(snapshot, path)])
    names = {part: name for name, ids in by_section.items() for part in ids}
    return {
        identifier: names.get(identifier, "") for identifier, _ in planner._parts[(snapshot, path)]
    }


async def head(case: LiveCase) -> str:
    response = await case.request("GET", "/v1/instance")
    assert response.status_code == 200, response.text
    return cast(str, response.json()["knowledge_revision"])


async def propose(
    case: LiveCase, actor: str, operations: list[dict[str, Any]]
) -> tuple[int, dict[str, Any]]:
    """Propose, submit and validate; returns the HTTP status and the final view."""
    response = await case.request(
        "POST",
        "/v1/changesets",
        actor=actor,
        json={
            "base_revision": await head(case),
            "operations": operations,
            "rationale": "M11 synthetic test change",
        },
        headers={"Idempotency-Key": hashlib.sha256(os.urandom(16)).hexdigest()[:32]},
    )
    if response.status_code not in (200, 201):
        return response.status_code, response.json()
    encoded = quote(str(response.json()["id"]), safe="")
    # Submitting runs validation; the result is `validated` or `rejected`.
    response = await case.request("POST", f"/v1/changesets/{encoded}/submit", actor=actor)
    if response.status_code != 200:
        return response.status_code, response.json()
    view = response.json()
    if view.get("state") != "validated":
        report = await case.request("GET", f"/v1/changesets/{encoded}/validation", actor=actor)
        view["codes"] = sorted(
            {
                item["code"]
                for item in report.json().get("diagnostics", [])
                if item["severity"] == "error"
            }
        )
    return 200, view


async def accept(case: LiveCase, view: dict[str, Any], reviewer: str) -> dict[str, Any]:
    assert view.get("state") == "validated", view
    encoded = quote(str(view["id"]), safe="")
    for step in ("approve", "apply"):
        response = await case.request(
            "POST",
            f"/v1/changesets/{encoded}/{step}",
            actor=reviewer,
            headers={"Idempotency-Key": hashlib.sha256(os.urandom(16)).hexdigest()[:32]},
        )
        assert response.status_code == 200, response.text
    assert response.json()["state"] == "applied", response.json()
    return cast(dict[str, Any], response.json())


def draft_ids(key: str, count: int) -> dict[str, Any]:
    return {
        "document": sp.ident(f"m11-draft/{key}", "document"),
        "draft": sp.ident(f"m11-draft/{key}/record", "record"),
        "parts": [sp.ident(f"m11-draft/{key}/{index}", "part") for index in range(count)],
    }


def draft_operations(
    template: Template,
    author: str,
    *,
    key: str = "d1",
    snapshots: tuple[str, ...] = ("a2", "b2"),
    contract: str = "a2",
    check: str | None = None,
    state: str = "draft",
    scope: str = "drafts-bob",
    lineage: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bob's draft: a Document with ordered parts, the draft record, and lineage."""
    planner: sp.Planner = template.loaded["planner"]
    spec = planner.fixture["draft"]
    ids = draft_ids(key, len(spec["parts"]))
    text = "".join(part["text"] + "\n\n" for part in spec["parts"])
    operations: list[dict[str, Any]] = [
        {
            "kind": "create",
            "scope_id": scope,
            "record": {
                "id": ids["document"],
                "types": [C1 + "Document"],
                "properties": {
                    DCT + "title": [sp.lit(spec["title"])],
                    C1 + "sourceRevision": [sp.lit("draft:" + key)],
                    C1 + "contentDigest": [sp.lit("sha256:" + sp.sha256(text.encode()))],
                },
            },
        }
    ]
    for index, (identifier, part) in enumerate(zip(ids["parts"], spec["parts"], strict=True)):
        operations.append(
            {
                "kind": "create",
                "record": {
                    "id": identifier,
                    "types": [C1 + "DocumentPart"],
                    "properties": {
                        C1 + "partOfDocument": [ids["document"]],
                        C1 + "orderKey": [sp.lit(sp.order_key(index + 1))],
                        C1 + "text": [sp.lit(part["text"])],
                        C1 + "partKind": [sp.lit(part["kind"])],
                    },
                },
            }
        )
    properties: dict[str, Any] = {
        S + "documentRef": [ids["document"]],
        S + "revises": [sp.file_id(*INVOICING)],
        S + "targetSnapshotRef": [sp.snapshot_id(item) for item in snapshots],
        S + "targetContractRef": [sp.file_id(contract, "openapi.json")],
        S + "authorRef": [author],
        S + "draftState": [sp.lit(state)],
    }
    if check is not None:
        properties[S + "applicabilityCheckRef"] = [check]
    operations.append(
        {
            "kind": "create",
            "scope_id": scope,
            "inherited_from": ids["document"],
            "record": {
                "id": ids["draft"],
                "types": [S + "DocumentationDraft"],
                "properties": properties,
            },
        }
    )
    sources: list[str] = []
    for index, part in enumerate(spec["parts"]):
        for source in part["lineage"] if lineage else []:
            if "contract" in source:
                source_part = sp.part_id(source["contract"], "openapi.json", 0)
                revision = planner.commit(source["contract"])
            else:
                found = planner._definition_part(
                    source["snapshot"], source["repository"], source["descriptor"]
                )
                assert found is not None
                source_part, revision = found, planner.commit(source["snapshot"])
            sources.append(source_part)
            claim_key = f"m11-lineage/{key}/{index}/{source_part}"
            claim = sp.ident(f"assertion/{claim_key}", "assertion")
            evidence = sp.evidence_record(
                claim_key,
                claim,
                source_part,
                revision,
                scope=scope,
                activity=sp.ident(f"activity/{claim_key}", "activity"),
            )
            del evidence["properties"][PROV + "wasGeneratedBy"]
            for record in (
                {
                    "id": claim,
                    "types": [C1 + "Assertion"],
                    "properties": {
                        RDF + "subject": [ids["parts"][index]],
                        RDF + "predicate": [PROV + "wasDerivedFrom"],
                        RDF + "object": [source_part],
                        C1 + "origin": [sp.lit("manual")],
                        C1 + "reviewState": [sp.lit("reported")],
                        C1 + "lifecycle": [sp.lit("active")],
                        C1 + "manualStatement": [sp.lit("true", "boolean")],
                        PROV + "wasAttributedTo": [author],
                        C1 + "evidence": [evidence["id"]],
                    },
                },
                {key: value for key, value in evidence.items() if key != "scope"},
            ):
                operations.append({"kind": "create", "scope_id": scope, "record": record})
    ids["sources"] = sources
    return operations, ids


def fixture_check(template: Template) -> str:
    spec = template.loaded["planner"].fixture["review_rule"]
    return rule.check_id(spec["target"], spec["checked_at"])


async def run_rule(
    case: LiveCase, template: Template, snapshots: list[str], contract: str, checked_at: str
) -> str:
    """Re-run the external rule for a target through the analyzer, as at load time."""
    planner = sp.Planner(sp.load_inputs(), template.loaded["principals"])
    planner.runs()
    spec = {"snapshots": snapshots, "contract": contract}
    await sp.apply_run(
        CaseLoader(case), rule.rule_run(planner, spec, checked_at), skip_complete=False
    )
    return rule.check_id(spec, checked_at)


async def rescope(case: LiveCase, resource: str, to_scope: str, actor: str) -> dict[str, Any]:
    response = await case.request(
        "POST",
        f"/v1/access-scopes/{quote(to_scope, safe='')}/bindings",
        actor=actor,
        json={"resource_id": resource},
    )
    assert response.status_code in (200, 201), response.text
    return cast(dict[str, Any], response.json())


async def operation_step(case: LiveCase, operation: str, step: str, actor: str) -> Any:
    return await case.request(
        "POST", f"/v1/security-operations/{quote(operation, safe='')}/{step}", actor=actor
    )
