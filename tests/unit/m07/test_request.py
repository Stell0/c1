from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from c1.context.request import (
    ContextRequest,
    IDSelector,
    LabelSelector,
    request_digest,
)


def payload(**changes: Any) -> dict[str, Any]:
    return {
        "profile": "graph-context",
        "profile_version": "1",
        "anchor": {"label": "Tesla"},
        **changes,
    }


def test_explicit_version_and_defaults() -> None:
    request = ContextRequest.model_validate(payload())
    assert request.profile_version == "1"
    assert request.budget.maximum == 65536
    assert request.formats == ["markdown", "structured"]
    assert request.topics == []
    value = payload()
    del value["profile_version"]
    with pytest.raises(ValidationError):
        ContextRequest.model_validate(value)


def test_explicit_selectors_preserve_labels_and_normalize_language() -> None:
    request = ContextRequest.model_validate(
        payload(
            anchor={"id": "urn:test:tesla"},
            topics=[
                "batteries",
                {"id": "urn:test:batteries"},
                {"label": "Storage", "language": "EN"},
            ],
            keywords_all=[{"text": "Tesla", "language": "EN"}],
        )
    )
    assert isinstance(request.anchor, IDSelector)
    assert request.topics[0] == "batteries"
    assert isinstance(request.topics[1], IDSelector)
    assert isinstance(request.topics[2], LabelSelector)
    assert request.topics[2].label == "Storage"
    assert request.topics[2].language == "en"
    assert request.keywords_all[0].keyword().normalized == "tesla"


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"profile": "../graph-context"},
        {"profile_version": 1},
        {"anchor": {"id": "urn:test:tesla", "label": "Tesla"}},
        {"anchor": {"label": "  "}},
        {"anchor": {"id": "relative"}},
        {"anchor": {"label": "Tesla", "language": "not_valid!"}},
        {"topics": [""]},
        {"topics": [{"label": "battery", "prompt": "execute"}]},
        {"topics": [1]},
        {"keywords_all": ["Tesla"]},
        {"formats": []},
        {"formats": ["markdown", "markdown"]},
        {"formats": ["html"]},
        {"budget": {"unit": "tokens", "maximum": 2048}},
        {"budget": {"maximum": 2047}},
        {"budget": {"maximum": 524289}},
        {"budget": {"maximum": "2048"}},
        {"budget": {"maximum": True}},
        {"budget": {"maximum": 2048, "model": "unknown"}},
        {"fields": ["capacity", "capacity"]},
        {"project_ref": "relative"},
        {"revision": "commit:../../head"},
        {"cursor": ""},
    ],
)
def test_strict_request_rejections(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ContextRequest.model_validate(payload(**changes))


@pytest.mark.parametrize("maximum", [2048, 65536, 524288])
def test_byte_budget_boundaries(maximum: int) -> None:
    assert (
        ContextRequest.model_validate(payload(budget={"maximum": maximum})).budget.maximum
        == maximum
    )


def test_digest_binds_semantics_and_allows_page_budget_change() -> None:
    first = ContextRequest.model_validate(payload(topics=["batteries"]))
    page = ContextRequest.model_validate(
        payload(
            topics=["batteries"], cursor="signed", revision="commit:abc", budget={"maximum": 2048}
        )
    )
    assert request_digest(first) == request_digest(page)
    assert request_digest(first) != request_digest(
        ContextRequest.model_validate(payload(topics=[]))
    )
    assert request_digest(first) != request_digest(
        ContextRequest.model_validate(payload(topics=["batteries"], formats=["markdown"]))
    )


def test_bare_topic_iris_are_explicit_ids_and_other_strings_are_labels() -> None:
    request = ContextRequest.model_validate(
        payload(topics=["urn:test:topic/batteries", "battery: storage"])
    )
    assert request.topics == [IDSelector(id="urn:test:topic/batteries"), "battery: storage"]
    explicit = ContextRequest.model_validate(
        payload(topics=[{"id": "urn:test:topic/batteries"}, "battery: storage"])
    )
    assert request_digest(request) == request_digest(explicit)
