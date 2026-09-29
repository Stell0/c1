from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from c1.changes.digest import canonical_json
from c1.context.budget import build_page, prepare_units
from c1.context.errors import ContextError
from c1.context.markdown import render_markdown
from c1.context.structured import parity_identifiers
from c1.documents.render import escape_markdown_text


def base() -> dict[str, Any]:
    return {
        "anchor_label": "Tesla <draft>",
        "revision": "revision-1",
        "interpretation": {
            "profile": "graph-context",
            "version": "1",
            "revision": "revision-1",
            "anchor": {"id": "urn:test:tesla"},
            "topics": ["batteries"],
            "narrowing": {},
        },
        "orientation": [
            {
                "node_ids": ["urn:test:tesla", "urn:test:battery"],
                "path": ["urn:test:edge"],
                "labels": ["Tesla", "hasProduct", "Battery"],
            }
        ],
        "fields": ["capacity", "cycle_life"],
        "field_predicates": {"capacity": "urn:test:capacity", "cycle_life": "urn:test:cycleLife"},
    }


def unit(index: int, *, excerpt: str = "Synthetic battery capacity.") -> dict[str, Any]:
    citation = {
        "id": f"urn:test:citation:{index}",
        "evidence_id": f"urn:test:evidence:{index}",
        "source_id": f"urn:test:source:{index}",
        "source_title": "Synthetic datasheet",
        "source_kind": "document",
        "source_revision": "source-v1",
        "evidence_source_revision": "source-v1",
        "evidence_target_id": "urn:test:part",
        "part_id": "urn:test:part",
        "document_id": "urn:test:document",
        "excerpt": excerpt,
        "excerpt_kind": "text",
        "excerpt_truncated": False,
        "imported_by": ["urn:test:import:1", "urn:test:import:2"],
        "corroboration": "duplicate_import",
    }
    metadata = {
        "review_state": "reported",
        "origin": "source",
        "lifecycle": "active",
        "valid_time": {"start": {"state": "unknown"}, "end": {"state": "unknown"}},
    }
    claim = {
        "assertion_id": f"urn:test:assertion:{index}",
        "value": {"kind": "literal", "lexical": "3.9", "datatype": "urn:test:decimal"},
        **metadata,
        "attributed_to": "urn:test:producer",
        "citations": [citation],
        "qualifiers": [
            {
                "assertion_id": f"urn:test:qualifier:{index}",
                "predicate": "urn:test:unit",
                "predicate_label": "unit",
                "value": {"kind": "literal", "lexical": "MWh", "datatype": "urn:test:string"},
                **metadata,
                "citations": [],
                "qualifiers": [],
                "incomplete": [],
            }
        ],
        "incomplete": [],
        "confidence": {"lexical": "0.8", "datatype": "urn:test:decimal"},
        "confidence_method": "uncalibrated producer score",
    }
    return {
        "id": f"urn:test:unit:{index}",
        "node_id": f"urn:test:battery:{index}",
        "node_label": f"Battery {index}",
        "node_types": ["urn:test:Battery"],
        "distance": 2,
        "predicate": "urn:test:capacity",
        "predicate_label": "capacity",
        "claims": [claim],
        "sources": 1,
        "imports": 2,
        "source_versions": [{"source_id": citation["source_id"], "revisions": ["source-v1"]}],
        "comparison": "agreement",
        "_dependencies": ["private checkpoint"],
    }


def page(
    units: list[dict[str, Any]],
    maximum: int = 65536,
    offset: int = 0,
    *,
    selected_base: dict[str, Any] | None = None,
    cursor_size: int = 32,
) -> dict[str, Any]:
    return build_page(
        selected_base or base(),
        prepare_units(units),
        offset=offset,
        maximum=maximum,
        cursor_for_offset=lambda i: str(i) + "a" * cursor_size,
    )


def test_safe_markdown_exact_structured_parity_and_no_mutation() -> None:
    malicious = "<script>![x](https://remote/image)</script>\n[ref]: https://remote/asset"
    original = unit(1, excerpt=malicious)
    original["node_label"] = malicious
    original["claims"][0]["value"]["lexical"] = malicious
    original["claims"][0]["qualifiers"][0]["value"]["lexical"] = malicious
    original["claims"][0]["citations"][0]["source_title"] = malicious
    original["roles"] = {
        "product": [{"id": "urn:test:product", "label": "Synthetic product", "types": []}],
        "version": [{"id": "urn:test:version", "label": "Synthetic version", "types": []}],
    }
    snapshot = deepcopy(original)
    result = page([original])
    markdown, structured = result["markdown"], result["structured"]
    assert original == snapshot
    assert "<" not in markdown and "![" not in markdown and "](https:" not in markdown
    assert "[ref]:" not in markdown
    assert "> " + escape_markdown_text(malicious.split("\n")[0]) in markdown
    assert structured["text"][0]["excerpt"] == malicious
    assert structured["facts"][0]["claims"][0]["value"]["lexical"] == malicious
    assert "private checkpoint" not in canonical_json(structured)
    assert structured["facts"][0]["roles"] == original["roles"]
    assert "Roles: " in markdown and "Synthetic product" in markdown
    assert "Synthetic version" in markdown
    assert "confidence method: uncalibrated producer score" in markdown
    assert [gap["field"] for gap in structured["gaps"]] == ["cycle_life"]
    assert structured["gaps"][0]["message"] == "not present in the returned material"
    digest = hashlib.sha256(
        canonical_json(parity_identifiers(structured["facts"])).encode()
    ).hexdigest()
    assert structured["format_parity_digest"] == digest
    assert "Format parity digest: " + digest in markdown
    assert markdown == render_markdown(structured)
    headings = re.findall(r"(?m)^## (.+)$", markdown)
    assert headings == [
        "Interpretation",
        "Orientation",
        "Facts",
        "Text",
        "Disagreements",
        "Gaps",
        "Sources",
        "Bounds",
    ]


def test_code_excerpt_is_fenced_safely_even_when_producer_calls_it_complete() -> None:
    selected = unit(1, excerpt="def x():\n    return '<script>'\n````\n")
    selected["claims"][0]["citations"][0]["excerpt_kind"] = "code-unit:python"
    result = page([selected])
    assert "`````text excerpt\n" in result["markdown"]
    assert "&lt;script&gt;" in result["markdown"]
    assert "complete unit" not in result["markdown"]
    assert (
        result["structured"]["text"][0]["excerpt"]
        == selected["claims"][0]["citations"][0]["excerpt"]
    )


def test_citation_numbers_are_global_and_sources_only_contain_selected_citations() -> None:
    units = [unit(i) for i in range(3)]
    units[2]["claims"][0]["qualifiers"][0]["citations"] = deepcopy(
        units[0]["claims"][0]["citations"]
    )
    prepared = prepare_units(units)
    assert [item["claims"][0]["citations"][0]["n"] for item in prepared] == [1, 2, 3]
    later = page(units, offset=2)["structured"]
    assert [citation["n"] for citation in later["sources"]] == [1, 3]
    assert [citation["n"] for citation in later["text"]] == [3, 1]
    assert "urn:test:evidence:1" not in canonical_json(later)


def test_complete_disagreement_and_qualifications_defer_as_one_unit() -> None:
    units = [unit(1), unit(2)]
    alternate = deepcopy(units[0]["claims"][0])
    alternate["assertion_id"] = "urn:test:competing"
    alternate["value"]["lexical"] = "3.6"
    units[0]["claims"].append(alternate)
    units[0]["disagreement"] = {
        "competing": True,
        "declared_conflict": True,
        "basis": "declared_single_value_known_overlap",
        "pairs": [["urn:test:assertion:1", "urn:test:competing"]],
    }
    units[1]["claims"][0]["citations"][0]["excerpt"] = "later " * 6000
    result = page(units, maximum=8500)
    assert [item["id"] for item in result["structured"]["facts"]] == [units[0]["id"]]
    assert len(result["structured"]["facts"][0]["claims"]) == 2
    assert all(claim["qualifiers"] for claim in result["structured"]["facts"][0]["claims"])
    assert result["structured"]["disagreements"][0]["declared_conflict"]
    assert result["bounds"]["truncated"] and result["bounds"]["deferred_units"] == 1
    assert result["bounds"]["rendered_bytes"] == len(result["markdown"].encode("utf-8"))


def test_budget_includes_actual_cursor_and_never_returns_nonadvancing_page() -> None:
    selected = unit(1, excerpt="é" * 10000)
    with pytest.raises(ContextError) as failure:
        page([selected], maximum=2048)
    assert failure.value.status == 422 and failure.value.code == "C1-CX-010"
    assert failure.value.details["minimum_required"] > 2048
    retry = page([selected], maximum=failure.value.details["minimum_required"])
    assert retry["bounds"]["included_units"] == 1
    assert retry["bounds"]["rendered_bytes"] == retry["bounds"]["maximum"]
    with pytest.raises(ContextError) as failure:
        page([unit(1), selected], maximum=8000, cursor_size=12000)
    assert failure.value.reason == "insufficient_budget"
    assert failure.value.details["minimum_required"] > 8000
    oversized_base = base()
    oversized_base["anchor_label"] = "huge " * 1000
    with pytest.raises(ContextError, match="insufficient_budget"):
        page([], maximum=2048, selected_base=oversized_base)


def test_nonmonotone_cursor_disappearance_can_allow_longer_prefix() -> None:
    units = [unit(1), unit(2)]
    result = page(units, maximum=10000, cursor_size=20000)
    assert len(result["structured"]["facts"]) == 2
    assert result["bounds"]["next_cursor"] is None
    assert result["bounds"]["rendered_bytes"] <= 10000


def test_continuation_is_contiguous_without_duplicates_and_deterministic() -> None:
    units = [unit(i, excerpt="text " * 200) for i in range(5)]
    offset, combined = 0, []
    while offset < len(units):
        result = page(units, maximum=7000, offset=offset)
        assert result == page(units, maximum=7000, offset=offset)
        assert result["bounds"]["rendered_bytes"] == len(result["markdown"].encode("utf-8"))
        assert result["bounds"]["rendered_bytes"] <= 7000
        selected = result["structured"]["facts"]
        assert selected
        combined.extend(selected)
        offset += len(selected)
    assert combined == page(units)["structured"]["facts"]


def test_expired_deadline_fails_without_output() -> None:
    with pytest.raises(ContextError) as failure:
        build_page(
            base(),
            prepare_units([unit(1)]),
            maximum=65536,
            cursor_for_offset=lambda offset: str(offset),
            deadline=time.monotonic() - 1,
        )
    assert failure.value.status == 503 and failure.value.code == "C1-CX-014"


def path_material() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_base = base()
    selected_base["fields"] = ["component_path"]
    selected_base["field_predicates"] = {
        "component_path": {
            "steps": [
                {
                    "predicate": "urn:test:hasBattery",
                    "direction": "out",
                    "target_types": ["urn:test:Battery"],
                },
                {
                    "predicate": "urn:test:hasComponent",
                    "direction": "out",
                    "target_types": ["urn:test:Component"],
                },
            ],
            "max_depth": 2,
        },
    }
    selected_base["orientation"] = [
        {
            "nodes": [
                {"id": "urn:test:tesla", "label": "Tesla", "types": ["urn:test:Company"]},
                {"id": "urn:test:battery:1", "label": "Battery", "types": ["urn:test:Battery"]},
            ],
            "edges": [
                {
                    "assertion_id": "urn:test:edge",
                    "predicate": "urn:test:hasBattery",
                    "subject": "urn:test:tesla",
                    "object": "urn:test:battery:1",
                }
            ],
        }
    ]
    relationship = unit(1)
    relationship["predicate"] = "urn:test:hasComponent"
    relationship["predicate_label"] = "hasComponent"
    relationship["claims"][0]["value"] = {
        "kind": "iri",
        "id": "urn:test:component",
        "label": "Component",
        "types": ["urn:test:Component"],
    }
    return selected_base, [relationship]


def test_path_field_follows_returned_connected_typed_relationships_without_mutation() -> None:
    selected_base, units = path_material()
    snapshot = deepcopy(selected_base)
    result = page(units, selected_base=selected_base)
    assert result["structured"]["gaps"] == []
    assert selected_base == snapshot
    assert "Tesla → urn:test:hasBattery → Battery" in result["markdown"]


@pytest.mark.parametrize("change", ["order", "direction", "target_type", "unrelated", "depth"])
def test_path_predicate_presence_alone_does_not_remove_gap(change: str) -> None:
    selected_base, units = path_material()
    path = selected_base["field_predicates"]["component_path"]
    if change == "order":
        path["steps"].reverse()
    elif change == "direction":
        path["steps"][0]["direction"] = "in"
    elif change == "target_type":
        path["steps"][1]["target_types"] = ["urn:test:OtherType"]
    elif change == "unrelated":
        units[0]["node_id"] = "urn:test:unrelated"
    else:
        path["max_depth"] = 1
    result = page(units, selected_base=selected_base)
    assert result["structured"]["gaps"] == [
        {
            "field": "component_path",
            "message": "not present in the returned material",
        }
    ]


def test_deferred_relationship_cannot_fill_returned_path_gap() -> None:
    selected_base, relationships = path_material()
    first = unit(1)
    later = relationships[0]
    later["id"] = "urn:test:unit:later"
    later["claims"][0]["citations"][0]["excerpt"] = "large later excerpt " * 2000
    units = [first, later]
    partial = page(units, maximum=7000, selected_base=selected_base)
    assert partial["bounds"]["included_units"] == 1
    assert partial["structured"]["gaps"][0]["field"] == "component_path"
    complete = page(units, maximum=100000, selected_base=selected_base)
    assert complete["structured"]["gaps"] == []


def test_inward_path_can_start_at_a_returned_unit_node() -> None:
    selected_base, units = path_material()
    component = unit(2)
    component.update(node_id="urn:test:component", node_types=["urn:test:Component"])
    units.append(component)
    path = selected_base["field_predicates"]["component_path"]
    path["steps"] = [
        {
            "predicate": "urn:test:hasComponent",
            "direction": "in",
            "target_types": ["urn:test:Battery"],
        },
        {
            "predicate": "urn:test:hasBattery",
            "direction": "in",
            "target_types": ["urn:test:Company"],
        },
    ]
    assert page(units, selected_base=selected_base)["structured"]["gaps"] == []


def test_equal_length_cursor_variants_have_identical_budget_selection_and_minimum() -> None:
    units = prepare_units([unit(1, excerpt="text " * 200), unit(2, excerpt="later " * 6000)])
    tokens = ["a" * 64, "_-" * 32, "A_0-" * 16]

    def token_cursor(token: str) -> Callable[[int], str]:
        def cursor(offset: int) -> str:
            return token

        return cursor

    results = [
        build_page(base(), units, maximum=10000, cursor_for_offset=token_cursor(token))
        for token in tokens
    ]
    assert {result["bounds"]["included_units"] for result in results} == {1}
    assert len({result["bounds"]["rendered_bytes"] for result in results}) == 1
    for token, result in zip(tokens, results, strict=True):
        assert "next\\_cursor: `" + token + "`" in result["markdown"]
        assert result["bounds"]["rendered_bytes"] == len(result["markdown"].encode())
        assert result["bounds"]["next_cursor"] == token
    minimums = []
    for token in tokens:
        with pytest.raises(ContextError) as failure:
            build_page(base(), units, maximum=2048, cursor_for_offset=token_cursor(token))
        minimums.append(failure.value.details["minimum_required"])
    assert len(set(minimums)) == 1


@pytest.mark.parametrize("token", ["", "unsafe`token", "unsafe\nline", "<script>", "token="])
def test_generated_cursor_alphabet_is_validated_before_raw_rendering(token: str) -> None:
    result = page([unit(1)])
    result["structured"]["bounds"]["next_cursor"] = token
    with pytest.raises(ValueError, match="unpadded base64url"):
        render_markdown(result["structured"])
