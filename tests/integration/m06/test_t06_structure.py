"""M06-T06: document references, ordering, selectors, and moves are validated."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from typing import Any, cast
from urllib.parse import quote

from c1.authorization.fga import resource_object, scope_object
from tests.integration.m03.conftest import LiveCase, live_case
from tests.integration.m04.conftest import changeset_path
from tests.integration.m06.conftest import (
    _apply_as_service,
    _knowledge_log,
    _service_request,
    _service_token,
    install_scoped_document,
)

CORE = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OA = "http://www.w3.org/ns/oa#"
PROV = "http://www.w3.org/ns/prov#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PART_PREFIX = "urn:c1:instance:dev:document-part/"


def _part(identifier: str, parent: str, key: str, text: str = "synthetic") -> dict[str, Any]:
    return {
        "id": identifier,
        "types": [CORE + "DocumentPart"],
        "properties": {
            CORE + "partOfDocument": [parent],
            CORE + "orderKey": [{"lexical": key, "datatype": XSD + "string"}],
            CORE + "text": [{"lexical": text, "datatype": XSD + "string"}],
            CORE + "partKind": [{"lexical": "text", "datatype": XSD + "string"}],
        },
    }


async def _all_binding_tuples(case: LiveCase) -> list[tuple[str, str, str]]:
    """Read every OpenFGA tuple; relation-only filters are invalid."""
    fga = cast(Any, case.fga)
    continuation = ""
    seen: set[str] = set()
    tuples: list[tuple[str, str, str]] = []
    for _ in range(100):
        payload = await fga._request(
            "POST",
            fga._path + "/read",
            json={
                "page_size": 100,
                "consistency": "HIGHER_CONSISTENCY",
                "continuation_token": continuation,
            },
        )
        for item in payload.get("tuples", []):
            key = item["key"]
            if key["relation"] == "bound_to":
                tuples.append((str(key["user"]), "bound_to", str(key["object"])))
        continuation = payload.get("continuation_token", "")
        if not continuation:
            return sorted(tuples)
        assert continuation not in seen, "OpenFGA read pagination did not advance"
        seen.add(continuation)
    raise AssertionError("OpenFGA read exceeded the test tuple bound")


async def _unchanged_state(case: LiveCase) -> tuple[object, ...]:
    journal_bindings = await case.journal.list("Binding")
    bindings = sorted(json.dumps(item, sort_keys=True) for item in journal_bindings)
    tuples = await _all_binding_tuples(case)
    return await case.knowledge.head(), await _knowledge_log(case), bindings, tuples


async def _reject(
    case: LiveCase,
    operations: list[dict[str, Any]],
    diagnostic_code: str | None,
    *,
    token: str | None = None,
    actor: str = "alice",
    status: int = 200,
) -> dict[str, Any]:
    before = await _unchanged_state(case)

    async def request(method: str, path: str, **kwargs: Any) -> Any:
        if token is not None:
            return await _service_request(case, token, method, path, **kwargs)
        if "json_body" in kwargs:
            kwargs["json"] = kwargs.pop("json_body")
        return await case.request(method, path, actor=actor, **kwargs)

    proposal = await request(
        "POST",
        "/v1/changesets",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json_body={"base_revision": before[0], "operations": operations},
    )
    assert proposal.status_code == 201
    identifier = proposal.json()["id"]
    result = await request("POST", changeset_path(identifier, "submit"))
    if result.status_code == 200 and result.json().get("state") == "submitted":
        result = await request("POST", changeset_path(identifier, "validate"))
    assert result.status_code == status
    report = await request("GET", changeset_path(identifier, "validation"))
    assert report.status_code == 200
    payload = report.json()
    assert payload["status"] == "rejected"
    if diagnostic_code is not None:
        actual_codes = {item["code"] for item in payload["diagnostics"]}
        safe_context = {
            "expected_code": diagnostic_code,
            "actual_codes": sorted(actual_codes),
            "operation_kinds": [operation.get("kind") for operation in operations],
            "targets": [
                operation.get("resource_id") or operation.get("record", {}).get("id")
                for operation in operations
            ],
        }
        assert diagnostic_code in actual_codes, safe_context
    else:
        denied = [item for item in payload["permission_preview"] if not item["allowed"]]
        assert denied
        assert all(item["reason"] == "permission_denied" for item in denied)
        if status == 403:
            assert payload["diagnostics"] == []
    if status == 403:
        denied = [item for item in payload["permission_preview"] if not item["allowed"]]
        assert denied
        assert all(item["reason"] == "permission_denied" for item in denied)
    assert await _unchanged_state(case) == before
    return {
        "diagnostics": payload["diagnostics"],
        "permission_preview": payload["permission_preview"],
    }


async def _apply_as_actor(case: LiveCase, actor: str, operation: dict[str, Any]) -> tuple[str, str]:
    proposal = await case.request(
        "POST",
        "/v1/changesets",
        actor=actor,
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={"base_revision": await case.knowledge.head(), "operations": [operation]},
    )
    assert proposal.status_code == 201
    identifier = proposal.json()["id"]
    validated = await case.request("POST", changeset_path(identifier, "submit"), actor=actor)
    assert validated.status_code == 200
    if validated.json().get("state") == "submitted":
        validated = await case.request("POST", changeset_path(identifier, "validate"), actor=actor)
    assert validated.status_code == 200 and validated.json()["state"] == "validated"
    approved = await case.request("POST", changeset_path(identifier, "approve"), actor="carol")
    assert approved.status_code == 200
    applied = await case.request(
        "POST",
        changeset_path(identifier, "apply"),
        actor="carol",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert applied.status_code == 200 and applied.json()["state"] == "applied"
    return cast(str, validated.json()["state"]), cast(str, applied.json()["state"])


def test_t06_structure_validation_is_atomic() -> None:
    async def run() -> None:
        async with live_case() as case:
            fixture, scopes, _revision1, _revision2 = await install_scoped_document(case)
            token = await _service_token(case)
            document_id = fixture["document_id"]

            malformed = {
                "kind": "create",
                "scope_id": scopes["doc-public"],
                "record": _part(PART_PREFIX + str(uuid.uuid4()), document_id, "bad key!"),
            }
            await _reject(case, [malformed], "C1-DC-002", token=token)

            insertion = {
                "kind": "create",
                "scope_id": scopes["doc-public"],
                "record": _part(PART_PREFIX + str(uuid.uuid4()), document_id, "H"),
            }
            await _reject(case, [insertion], None, status=403)
            await case.grant(scopes["doc-public"], "alice", "creator")

            missing_parent = {
                "kind": "create",
                "scope_id": scopes["doc-public"],
                "record": _part(
                    PART_PREFIX + str(uuid.uuid4()), "urn:c1:instance:dev:document/missing", "H"
                ),
            }
            missing_report = await _reject(case, [missing_parent], "C1-CS-010", status=403)
            unreadable_parent = {
                **missing_parent,
                "record": _part(PART_PREFIX + str(uuid.uuid4()), fixture["notes_id"], "H"),
            }
            unreadable_report = await _reject(case, [unreadable_parent], "C1-CS-010", status=403)
            for report in (missing_report, unreadable_report):
                preview = report["permission_preview"]
                assert len(preview) == 1
                assert preview[0]["allowed"] is False
                assert preview[0]["reason"] == "permission_denied"
                assert {item["code"] for item in report["diagnostics"]} == {"C1-CS-010"}
            assert missing_report == unreadable_report

            nested_record = _part(PART_PREFIX + str(uuid.uuid4()), document_id, "H")
            nested_record["properties"][CORE + "parentPart"] = [
                "urn:c1:instance:dev:document-part/00000071-0000-4000-8000-000000000000"
            ]
            nested = {"kind": "create", "scope_id": scopes["doc-public"], "record": nested_record}
            await _reject(case, [nested], "C1-IX-011", token=token)

            entity_id = "urn:c1:instance:dev:entity/" + str(uuid.uuid4())
            assertion_id = "urn:c1:instance:dev:assertion/" + str(uuid.uuid4())
            evidence_id = "urn:c1:instance:dev:evidence/" + str(uuid.uuid4())
            selector_id = "urn:c1:instance:dev:selector/" + str(uuid.uuid4())
            p2_id = PART_PREFIX + "00000072-0000-4000-8000-000000000000"
            selector_operations: list[dict[str, Any]] = [
                {
                    "kind": "create",
                    "scope_id": scopes["doc-public"],
                    "record": {
                        "id": entity_id,
                        "types": [CORE + "Entity"],
                        "properties": {
                            SKOS + "prefLabel": [
                                {
                                    "lexical": "Synthetic selector subject",
                                    "datatype": RDF + "langString",
                                    "language": "en",
                                }
                            ],
                            CORE + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
                        },
                    },
                },
                {
                    "kind": "create",
                    "scope_id": scopes["doc-public"],
                    "record": {
                        "id": assertion_id,
                        "types": [CORE + "Assertion"],
                        "properties": {
                            RDF + "subject": [entity_id],
                            RDF + "predicate": [CORE + "worksFor"],
                            RDF + "object": [entity_id],
                            CORE + "origin": [{"lexical": "manual", "datatype": XSD + "string"}],
                            CORE + "reviewState": [
                                {"lexical": "reported", "datatype": XSD + "string"}
                            ],
                            CORE + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
                            CORE + "manualStatement": [
                                {"lexical": "true", "datatype": XSD + "boolean"}
                            ],
                            PROV + "wasAttributedTo": ["urn:c1:agent:m06-fixture"],
                        },
                    },
                },
                {
                    "kind": "create",
                    "scope_id": scopes["doc-public"],
                    "record": {
                        "id": selector_id,
                        "types": [CORE + "Selector"],
                        "properties": {
                            CORE + "selectorKind": [
                                {"lexical": "TextQuoteSelector", "datatype": XSD + "string"}
                            ],
                            OA + "exact": [
                                {"lexical": "string absent from part", "datatype": XSD + "string"}
                            ],
                        },
                    },
                },
                {
                    "kind": "create",
                    "scope_id": scopes["doc-public"],
                    "record": {
                        "id": evidence_id,
                        "types": [CORE + "Evidence"],
                        "properties": {
                            CORE + "assertionRef": [assertion_id],
                            OA + "hasSource": [p2_id],
                            CORE + "sourceRevision": [
                                {"lexical": "handbook-v1", "datatype": XSD + "string"}
                            ],
                            OA + "hasSelector": [selector_id],
                        },
                    },
                },
            ]
            await _reject(case, selector_operations, "C1-DC-005", token=token)
            wrong_revision = copy.deepcopy(selector_operations)
            wrong_revision[2]["record"]["properties"][OA + "exact"][0]["lexical"] = "public"
            wrong_revision[3]["record"]["properties"][CORE + "sourceRevision"][0]["lexical"] = (
                "handbook-v0"
            )
            await _reject(case, wrong_revision, "C1-DC-009", token=token)

            # A reader/contributor of the old team scope cannot move a part into
            # the legal document without contribution authority there.
            await case.grant(scopes["doc-team"], "bob", "contributor")
            p3_id = PART_PREFIX + "00000073-0000-4000-8000-000000000000"
            p3 = next(item for item in fixture["revision1"] if item["id"] == p3_id)
            retyped = {
                "kind": "replace",
                "resource_id": p3["id"],
                "record": {
                    "id": p3["id"],
                    "types": [CORE + "Entity"],
                    "properties": {
                        SKOS + "prefLabel": [
                            {
                                "lexical": "Unauthorized part retype",
                                "datatype": RDF + "langString",
                                "language": "en",
                            }
                        ],
                        CORE + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
                    },
                },
                "reason": "Attempt to retype a DocumentPart as an Entity",
            }
            await _reject(case, [retyped], None, actor="bob", status=403)
            moved = {
                "kind": "replace",
                "resource_id": p3["id"],
                "record": {
                    **{key: p3[key] for key in ("id", "types", "properties")},
                    "properties": {
                        **p3["properties"],
                        CORE + "partOfDocument": [fixture["notes_id"]],
                    },
                },
                "reason": "Denied cross-scope document move fixture",
            }
            await _reject(case, [moved], "C1-CS-010", actor="bob", status=403)

            # The writer reads only public parts. Guessing a protected rank is
            # as successful as choosing an unrelated rank, with no occupancy check.
            await case.grant(scopes["doc-public"], "alice", "contributor")
            hidden = await case.request(
                "GET", "/v1/resources/" + quote(p3["id"], safe=""), actor="alice"
            )
            assert hidden.status_code == 404
            outcomes = []
            inheriting_part = ""
            inheriting_binding: dict[str, Any] | None = None
            for rank in ("C", "Z"):
                identifier = PART_PREFIX + str(uuid.uuid4())
                operation = {
                    "kind": "create",
                    "record": _part(identifier, document_id, rank),
                }
                outcomes.append(await _apply_as_actor(case, "alice", operation))
                binding = await case.journal.get("Binding", identifier)
                assert binding is not None
                assert binding["scope_id"] == scopes["doc-public"]
                assert binding["inherited_from"] == document_id
                assert binding["state"] == "active"
                assert await case.fga.bindings(resource_object(identifier)) == [
                    scope_object(scopes["doc-public"])
                ]
                if rank == "C":
                    inheriting_part = identifier
                    inheriting_binding = binding
            assert outcomes == [("validated", "applied"), ("validated", "applied")]

            move_inheriting = {
                "kind": "replace",
                "resource_id": inheriting_part,
                "record": _part(inheriting_part, fixture["notes_id"], "C"),
                "reason": "Move content while preserving its current security binding",
            }
            await _apply_as_service(case, token, [move_inheriting], "Security-independent move")
            assert await case.journal.get("Binding", inheriting_part) == inheriting_binding
            assert await case.fga.bindings(resource_object(inheriting_part)) == [
                scope_object(scopes["doc-public"])
            ]
            await case.grant(scopes["doc-legal"], "frank", "reader")
            destination = await case.request(
                "GET", "/v1/documents/" + quote(fixture["notes_id"], safe=""), actor="frank"
            )
            assert destination.status_code == 200
            assert inheriting_part not in {part["part_id"] for part in destination.json()["parts"]}

            # Equal ranks across independent scopes publish in canonical IRI
            # order even when the operations arrived in the opposite order.
            identifiers = sorted(PART_PREFIX + str(uuid.uuid4()) for _ in range(2))
            equal_rank = [
                {
                    "kind": "create",
                    "scope_id": scopes[scope],
                    "record": _part(identifier, document_id, "J"),
                }
                for identifier, scope in zip(
                    reversed(identifiers), ("doc-legal", "doc-public"), strict=True
                )
            ]
            await _apply_as_service(case, token, equal_rank, "Equal-rank structure fixture")
            reconstructed = await case.request(
                "GET", "/v1/documents/" + quote(document_id, safe=""), actor="carol"
            )
            assert reconstructed.status_code == 200
            assert [
                part["part_id"]
                for part in reconstructed.json()["parts"]
                if part["order_key"] == "J"
            ] == identifiers

    asyncio.run(run())
