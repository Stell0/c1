from __future__ import annotations

import pytest
from pydantic import ValidationError

from c1.api.routes.query import _bool
from c1.model.literals import RDF_LANG_STRING, XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, SKOS, AssertionRecord, EntityRecord
from c1.model.time import XSD, TimeBoundary, TimeInterval
from c1.query.filters import (
    AssertionFilters,
    QueryFilters,
    evaluate_assertion,
    evaluate_entity,
    filter_digest,
    order_key,
    valid_at_status,
)
from c1.query.plan import QueryPlanError

PERSON = "urn:test:person"
COMPANY = "urn:test:company"
HIDDEN = "urn:test:hidden"
WORKS = "urn:test:worksFor"
REVENUE = "urn:test:revenue"
KW = "urn:test:keyword"


def test_boolean_filter_requires_explicit_true_or_false() -> None:
    assert _bool("true") is True
    assert _bool("FALSE") is False
    with pytest.raises(QueryPlanError, match="invalid_boolean"):
        _bool("yes")
    with pytest.raises(ValidationError):
        QueryFilters.model_validate({"include_unknown": "yes"})


def lit(text: str, datatype: str = XSD_STRING, language: str | None = None) -> LiteralValue:
    return LiteralValue(lexical=text, datatype=datatype, language=language)


def entity() -> NodeRecord:
    return EntityRecord(
        id=PERSON,
        types=[C1 + "Entity", "urn:test:Person"],
        labels=[lit("Ada Example", RDF_LANG_STRING, "en")],
        aliases=[lit("Ada E.", RDF_LANG_STRING, "en")],
        keywords=[KW],
        project_references=["urn:test:project"],
    ).to_node()


def keyword() -> NodeRecord:
    return NodeRecord(
        id=KW,
        types=[C1 + "Keyword"],
        properties={
            C1 + "keywordText": [lit("  Batteries  ")],
            C1 + "keywordLanguage": [lit("en")],
        },
    )


def assertion(id_suffix: str, predicate: str, obj: str | LiteralValue) -> NodeRecord:
    return AssertionRecord(
        id=f"urn:test:assertion:{id_suffix}",
        subject=PERSON,
        predicate=predicate,
        object=obj,
        origin="manual",
        valid_interval="urn:test:interval",
    ).to_node()


def interval(start: TimeBoundary, end: TimeBoundary) -> TimeInterval:
    return TimeInterval(start=start, end=end)


def known(value: str, datatype: str = XSD + "gYear") -> TimeBoundary:
    return TimeBoundary(state="known", lexical=value, datatype=datatype)


def test_combined_filters_and_authorized_joins() -> None:
    relations = (
        assertion("works", WORKS, COMPANY),
        assertion("revenue", REVENUE, lit("42.5", XSD + "decimal")),
    )
    filters = QueryFilters.model_validate(
        {
            "types": ["urn:test:Person"],
            "keywords_all": [{"text": "BATTERIES", "language": "en"}],
            "label": {"text": "ada", "mode": "prefix", "language": "en"},
            "alias": {"text": "ada e.", "mode": "exact"},
            "properties": [
                {
                    "predicate": REVENUE,
                    "op": "ge",
                    "value": {"lexical": "42.50", "datatype": XSD + "decimal"},
                }
            ],
            "relations": [{"predicate": WORKS, "target_id": COMPANY}],
            "scope_ids": ["dir-shared"],
            "project_ref": "urn:test:project",
            "valid_at": "2025-05-01T00:00:00Z",
        }
    )
    period = interval(known("2025Z"), known("2026Z"))
    result = evaluate_entity(
        entity(),
        filters,
        keywords_by_id={KW: keyword()},
        assertions=relations,
        readable_entity_ids=frozenset({PERSON, COMPANY}),
        intervals_by_id={"urn:test:interval": period},
        scope_id="dir-shared",
    )
    assert result.status == "match"
    assert "relations" in result.matched_filters
    assert (
        evaluate_entity(
            entity(),
            filters,
            keywords_by_id={KW: keyword()},
            assertions=relations,
            readable_entity_ids=frozenset({PERSON}),
            intervals_by_id={"urn:test:interval": period},
            scope_id="dir-shared",
        ).status
        == "no_match"
    )
    assert (
        evaluate_entity(
            entity(),
            filters,
            keywords_by_id={KW: keyword()},
            assertions=relations[1:],
            readable_entity_ids=frozenset({PERSON, COMPANY}),
            intervals_by_id={"urn:test:interval": period},
            scope_id="dir-shared",
        ).status
        == "no_match"
    )


def test_exact_keyword_language_and_hidden_keyword_node() -> None:
    filters = QueryFilters(keywords_any=[{"text": "batteries", "language": "en"}])  # type: ignore[list-item]
    assert evaluate_entity(entity(), filters, keywords_by_id={KW: keyword()}).status == "match"
    assert evaluate_entity(entity(), filters, keywords_by_id={}).status == "no_match"
    french = QueryFilters.model_validate(
        {"keywords_any": [{"text": "batteries", "language": "fr"}]}
    )
    assert evaluate_entity(entity(), french, keywords_by_id={KW: keyword()}).status == "no_match"


def test_valid_time_unknown_is_separate_and_exclusive_end() -> None:
    period = interval(known("2025Z"), known("2026Z"))
    assert valid_at_status(period, "2025-06-01T00:00:00Z") == "match"
    assert valid_at_status(period, "2027-01-01T00:00:00Z") == "no_match"
    unknown = interval(TimeBoundary(state="unknown"), known("2026Z"))
    assert valid_at_status(unknown, "2025-06-01T00:00:00Z") == "indeterminate"
    a = assertion("works", WORKS, COMPANY)
    strict = AssertionFilters(valid_at="2025-06-01T00:00:00Z")
    broad = AssertionFilters(valid_at="2025-06-01T00:00:00Z", include_unknown=True)
    assert evaluate_assertion(a, strict, interval=unknown).status == "no_match"
    assert evaluate_assertion(a, broad, interval=unknown).status == "indeterminate"
    assert evaluate_assertion(a, broad, interval=unknown).rule == "unknown_validity"


def test_typed_literal_comparison_and_total_order() -> None:
    amount = assertion("revenue", REVENUE, lit("100", XSD + "integer"))
    numeric = QueryFilters.model_validate(
        {
            "properties": [
                {
                    "predicate": REVENUE,
                    "op": "gt",
                    "value": {"lexical": "99.5", "datatype": XSD + "decimal"},
                }
            ]
        }
    )
    assert evaluate_entity(entity(), numeric, assertions=(amount,)).status == "match"
    wrong_type = QueryFilters.model_validate(
        {
            "properties": [
                {
                    "predicate": REVENUE,
                    "op": "eq",
                    "value": {"lexical": "100", "datatype": XSD_STRING},
                }
            ]
        }
    )
    assert evaluate_entity(entity(), wrong_type, assertions=(amount,)).status == "no_match"
    assert order_key(entity(), "label") == ("ada example", PERSON)
    assert order_key(entity(), "id") == (PERSON, PERSON)
    assert order_key(entity(), "recorded", recorded_at="2025-01-01T00:00:00Z") == (
        "2025-01-01T00:00:00Z",
        PERSON,
    )


def test_typed_temporal_bounds() -> None:
    year = assertion("year", "urn:test:published", lit("2025Z", XSD + "gYear"))
    older = QueryFilters.model_validate(
        {
            "properties": [
                {
                    "predicate": "urn:test:published",
                    "op": "gt",
                    "value": {"lexical": "2024Z", "datatype": XSD + "gYear"},
                }
            ]
        }
    )
    overlapping = QueryFilters.model_validate(
        {
            "properties": [
                {
                    "predicate": "urn:test:published",
                    "op": "gt",
                    "value": {"lexical": "2025-06-01Z", "datatype": XSD + "date"},
                }
            ]
        }
    )
    assert evaluate_entity(entity(), older, assertions=(year,)).status == "match"
    assert evaluate_entity(entity(), overlapping, assertions=(year,)).status == "no_match"


@pytest.mark.parametrize(
    "payload",
    [
        {"woql": "true"},
        {"ids": ["urn:test:x"] * 201},
        {"types": ["not an iri"]},
        {"scope_ids": ["urn:test:scope"]},
        {"revision": "commit:../unsafe"},
        {"limit": 201},
        {"valid_at": "2025-01-01T00:00:00"},
        {"label": {"text": "Ada", "mystery": "x"}},
        {"keywords_all": [{"text": "x", "normalized": "x"}]},
        {"properties": [{"predicate": REVENUE, "op": "gt", "value": COMPANY}]},
    ],
)
def test_unknown_or_invalid_filter_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        QueryFilters.model_validate(payload)


def test_assertion_pagination_grammar() -> None:
    assert AssertionFilters(limit=200, revision="abc_DEF-1").limit == 200
    with pytest.raises(ValidationError):
        AssertionFilters(limit=201)
    with pytest.raises(ValidationError):
        AssertionFilters(revision="branch:../unsafe")


def test_digest_excludes_cursor_and_limit_but_binds_semantics() -> None:
    one = QueryFilters.model_validate({"label": {"text": "Ada"}, "limit": 20})
    two = QueryFilters.model_validate({"label": {"text": "Ada"}, "limit": 100, "cursor": "ignored"})
    three = QueryFilters.model_validate({"label": {"text": "Bob"}})
    assert filter_digest(one) == filter_digest(two)
    assert filter_digest(one) != filter_digest(three)
    explicit = QueryFilters.model_validate({"label": {"text": "Ada"}, "revision": "commit-1"})
    assert filter_digest(one) == filter_digest(explicit)


def test_properties_are_assertions_not_entity_shortcuts() -> None:
    node = NodeRecord(
        id=PERSON,
        types=[C1 + "Entity"],
        properties={REVENUE: [lit("100", XSD + "integer")], SKOS + "prefLabel": [lit("Ada")]},
    )
    filters = QueryFilters.model_validate({"properties": [{"predicate": REVENUE, "op": "exists"}]})
    assert evaluate_entity(node, filters).status == "no_match"
