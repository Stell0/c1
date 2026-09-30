"""M09 D1: strict target/goal grammar; graph-profile digests are unchanged."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from c1.context.request import ContextRequest, TargetSelector, request_digest

SNAPSHOT = "urn:c1:instance:dev:entity/00000000-0000-4000-8000-000000000001"


def _request(**changes: Any) -> ContextRequest:
    return ContextRequest.model_validate(
        {
            "profile": "graph-context",
            "profile_version": "1",
            "anchor": {"label": "Tesla"},
            **changes,
        }
    )


def test_graph_request_digest_is_the_m07_digest() -> None:
    request = _request(topics=["batteries"])
    value = request.model_dump(
        mode="json", exclude={"cursor", "budget", "revision", "target", "goal"}
    )
    expected = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert request_digest(request) == expected
    assert "target" not in value and "goal" not in value


def test_target_and_goal_are_bound_into_the_digest() -> None:
    base = _request(target={"snapshots": [SNAPSHOT]}, goal="conformance")
    assert request_digest(base) != request_digest(
        _request(target={"snapshots": [SNAPSHOT]}, goal="characterization")
    )
    assert request_digest(base) != request_digest(_request(goal="conformance"))


@pytest.mark.parametrize(
    "target",
    [
        {},
        {"target_set_id": SNAPSHOT, "snapshots": [SNAPSHOT]},
        {"snapshots": [SNAPSHOT, SNAPSHOT]},
        {"snapshots": ["not an iri"]},
        {"branches": [{"repository": SNAPSHOT, "branch": "main"}], "as_of": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_targets_are_rejected(target: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _request(target=target)


def test_goal_is_closed() -> None:
    with pytest.raises(ValidationError):
        _request(goal="summary")
    assert TargetSelector(target_set_id=SNAPSHOT).spec() == {"target_set_id": SNAPSHOT}
