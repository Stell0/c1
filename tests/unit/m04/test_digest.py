"""Canonical request digest and knowledge receipt contract."""

from __future__ import annotations

import hashlib
import json

import pytest

from c1.changes.digest import canonical_json, receipt_message, request_digest
from c1.changes.models import CreateOperation


def test_sorted_compact_json_and_digest() -> None:
    operation = CreateOperation(record={"z": "é", "a": {"b": 2, "a": 1}}, scope_id="S")
    payload = {
        "base_revision": "H",
        "operations": [
            {"kind": "create", "record": {"a": {"a": 1, "b": 2}, "z": "é"}, "scope_id": "S"}
        ],
        "rationale": "why",
    }
    expected = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert canonical_json(payload) == expected
    assert request_digest("H", [operation], "why") == hashlib.sha256(expected.encode()).hexdigest()


def test_digest_sensitive_to_order_base_and_rationale() -> None:
    a = {"kind": "install_profile", "profile": "a"}
    b = {"kind": "install_profile", "profile": "b"}
    baseline = request_digest("H", [a, b], None)
    assert baseline != request_digest("H", [b, a], None)
    assert baseline != request_digest("H2", [a, b], None)
    assert baseline != request_digest("H", [a, b], "reason")


def test_non_json_values_rejected() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        canonical_json({"x": float("nan")})
    with pytest.raises(ValueError, match="JSON-compatible"):
        canonical_json({"x": object()})


def test_receipt_version_two_and_identifier_fields() -> None:
    digest = "a" * 64
    message = receipt_message(
        changeset_id="cs-1",
        attempt=2,
        principal_id="issuer|subject",
        repository="db",
        digest=digest,
    )
    assert json.loads(message) == {
        "c1": 2,
        "changeset": "cs-1",
        "attempt": 2,
        "principal": "issuer|subject",
        "repository": "db",
        "digest": digest,
    }
    with pytest.raises(ValueError, match="digest"):
        receipt_message(
            changeset_id="cs-1", attempt=1, principal_id="p", repository="db", digest="bad"
        )
