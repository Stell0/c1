"""Ordered path relevance, security negatives, and aggregate context bounds."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from c1.context.errors import ContextError
from c1.context.profiles import ContextProfile, load_context_profile
from c1.context.request import ContextRequest
from c1.context.select import select_context
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, RDF, SKOS

B = "urn:c1:ns:batteries#"
SUBJECT = "http://purl.org/dc/terms/subject"


def lit(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD_STRING)


def node(name: str, kind: str = C1 + "Entity", **properties: Any) -> NodeRecord:
    return NodeRecord(
        id="urn:test:" + name,
        types=[kind],
        properties={
            SKOS + "prefLabel": [lit(name)],
            **properties,
        },
    )


def edge(
    name: str, subject: NodeRecord, predicate: str, target: NodeRecord, *, active: bool = True
) -> NodeRecord:
    return node(
        name,
        C1 + "Assertion",
        **{
            RDF + "subject": [subject.id],
            RDF + "predicate": [predicate],
            RDF + "object": [target.id],
            C1 + "lifecycle": [lit("active" if active else "retracted")],
        },
    )


def fixture() -> tuple[dict[str, NodeRecord], ContextProfile, ContextRequest, str]:
    profile = load_context_profile(Path("profiles/context/graph-context.json"))
    anchor = node("Tesla")
    product, battery, version = (
        node("Megapack", B + "Product"),
        node("Battery", B + "Battery"),
        node("M-B3", B + "BatteryVersion"),
    )
    prefix_product, prefix_version = (
        node("Vehicle", B + "Product"),
        node("V-B2", B + "BatteryVersion"),
    )
    solar, instrument = node("Solar", B + "Product"), node("TSLA")
    scheme = node("scheme", SKOS + "ConceptScheme").model_copy(update={"id": profile.topic_scheme})
    topic = node("batteries", SKOS + "Concept", **{SKOS + "inScheme": [scheme.id]})
    storage = node("storage-keyword", C1 + "Keyword", **{C1 + "keywordText": [lit("storage")]})
    version = version.model_copy(
        update={
            "properties": {
                **version.properties,
                C1 + "keyword": [storage.id],
                C1 + "projectReference": ["urn:test:project"],
            }
        }
    )
    records = [
        anchor,
        product,
        battery,
        version,
        prefix_product,
        prefix_version,
        solar,
        instrument,
        scheme,
        topic,
        storage,
        edge("ap", anchor, B + "hasProduct", product),
        edge("pb", product, B + "hasComponent", battery),
        edge("bv", battery, B + "hasVersion", version),
        edge("avp", anchor, B + "hasProduct", prefix_product),
        edge("vpv", prefix_product, B + "hasComponent", prefix_version),
        edge("as", anchor, B + "hasProduct", solar),
        edge("ai", anchor, B + "hasInstrument", instrument),
        edge("vtopic", version, SUBJECT, topic),
        edge("prefix-topic", prefix_version, SUBJECT, topic),
    ]
    request = ContextRequest.model_validate(
        {
            "profile": "graph-context",
            "profile_version": "1",
            "anchor": {"id": anchor.id},
            "topics": ["batteries"],
        }
    )
    return {item.id: item for item in records}, profile, request, topic.id


def select(
    records: dict[str, NodeRecord],
    profile: ContextProfile,
    request: ContextRequest,
    topics: list[str],
) -> dict[str, Any]:
    return select_context(
        records, "urn:test:Tesla", topics, profile, request, deadline=time.monotonic() + 10
    )


def test_graph_matches_without_anchor_keyword_and_excludes_unrelated_orientation() -> None:
    records, profile, request, topic = fixture()
    result = select(records, profile, request, [topic])
    assert [item["node_id"] for item in result["matched"]] == ["urn:test:V-B2", "urn:test:M-B3"]
    assert result["matched"][0]["distance"] == 2  # A typed path prefix may match.
    assert result["matched"][1]["path"] == ["urn:test:ap", "urn:test:pb", "urn:test:bv"]
    assert "Solar" not in str(result["orientation"])
    assert "TSLA" not in str(result["orientation"])
    assert result["traversal"]["truncated"] is False
    assert [
        item["node_id"]
        for item in select(records, profile, request.model_copy(update={"topics": []}), [])[
            "matched"
        ]
    ] == [item["node_id"] for item in result["matched"]]


def test_hidden_path_topic_or_endpoint_cannot_cause_a_match() -> None:
    records, profile, request, topic = fixture()
    baseline = select(records, profile, request, [topic])
    solar = records["urn:test:Solar"]
    direct = solar.model_copy(update={"properties": {**solar.properties, SUBJECT: [topic]}})
    # Direct shortcuts and references are not independently authorized claims.
    assert select({**records, direct.id: direct}, profile, request, [topic]) == baseline
    for hidden in ["urn:test:pb", "urn:test:bv", "urn:test:M-B3", "urn:test:vtopic"]:
        restricted = {key: value for key, value in records.items() if key != hidden}
        assert [
            item["node_id"] for item in select(restricted, profile, request, [topic])["matched"]
        ] == ["urn:test:V-B2"]
    # A readable endpoint and readable topic still do not reveal a hidden topic assertion.
    assert select(records, profile, request, ["urn:test:hidden-topic"])["matched"] == []
    inactive = records["urn:test:vtopic"].model_copy(
        update={
            "properties": {
                **records["urn:test:vtopic"].properties,
                C1 + "lifecycle": [lit("retracted")],
            }
        }
    )
    assert [
        item["node_id"]
        for item in select({**records, inactive.id: inactive}, profile, request, [topic])["matched"]
    ] == ["urn:test:V-B2"]


def test_predicate_order_direction_and_target_types_are_enforced() -> None:
    records, profile, request, topic_id = fixture()
    anchor, topic = records["urn:test:Tesla"], records[topic_id]
    product, version = (
        node("WrongProduct", B + "Product"),
        node("WrongVersion", B + "BatteryVersion"),
    )
    wrong = [
        product,
        version,
        edge("wrong-first", anchor, B + "hasComponent", product),
        edge("wrong-second", product, B + "hasProduct", version),
        edge("wrong-topic", version, SUBJECT, topic),
    ]
    assert (
        select({**records, **{item.id: item for item in wrong}}, profile, request, [topic_id])[
            "matched"
        ]
        == select(records, profile, request, [topic_id])["matched"]
    )
    reversed_edge = edge(
        "reverse-component", version, B + "hasComponent", records["urn:test:Megapack"]
    )
    bad_type = edge("wrong-type", anchor, B + "hasProduct", version)
    assert (
        select(
            {
                **records,
                **{item.id: item for item in [version, reversed_edge, bad_type, wrong[-1]]},
            },
            profile,
            request,
            [topic_id],
        )["matched"]
        == select(records, profile, request, [topic_id])["matched"]
    )
    inverse = profile.model_copy(
        update={
            "paths": [
                profile.paths[0].model_copy(
                    update={
                        "steps": [profile.paths[0].steps[0].model_copy(update={"direction": "in"})],
                    }
                )
            ],
            "target_types": [B + "Product"],
        }
    )
    back = edge("inverse", product, B + "hasProduct", anchor)
    result = select(
        {**records, product.id: product, back.id: back},
        inverse,
        request.model_copy(update={"topics": []}),
        [],
    )
    assert [item["node_id"] for item in result["matched"]] == [product.id]


def test_shortest_path_and_assertion_id_ties_are_deterministic() -> None:
    records, profile, request, topic = fixture()
    earlier = records["urn:test:ap"].model_copy(update={"id": "urn:test:0-first"})
    expanded = {**records, earlier.id: earlier}
    first = select(expanded, profile, request, [topic])
    second = select(dict(reversed(list(expanded.items()))), profile, request, [topic])
    assert first == second
    assert first["matched"][1]["path"][0] == earlier.id
    shorter = edge(
        "shorter", records["urn:test:Megapack"], B + "hasComponent", records["urn:test:M-B3"]
    )
    result = select({**expanded, shorter.id: shorter}, profile, request, [topic])
    match = next(item for item in result["matched"] if item["node_id"] == "urn:test:M-B3")
    assert match["distance"] == 2
    assert match["path"] == [earlier.id, shorter.id]


def test_keyword_and_project_narrowing_reuses_exact_m05_semantics() -> None:
    records, profile, request, topic = fixture()
    positive_updates: list[dict[str, Any]] = [
        {"keywords_all": [{"text": "STORAGE"}]},
        {"keywords_any": [{"text": "storage"}, {"text": "tesla"}]},
        {"project_ref": "urn:test:project"},
    ]
    for updates in positive_updates:
        narrowed = ContextRequest.model_validate({**request.model_dump(), **updates})
        assert [
            item["node_id"] for item in select(records, profile, narrowed, [topic])["matched"]
        ] == ["urn:test:M-B3"]
    negative_updates: list[dict[str, Any]] = [
        {"keywords_all": [{"text": "tesla"}]},
        {"keywords_any": [{"text": "stor"}]},
        {"project_ref": "urn:test:other-project"},
        {"keywords_all": [{"text": "storage", "language": "en"}]},
    ]
    for updates in negative_updates:
        narrowed = ContextRequest.model_validate({**request.model_dump(), **updates})
        assert select(records, profile, narrowed, [topic])["matched"] == []
    hidden_keyword = {
        key: value for key, value in records.items() if key != "urn:test:storage-keyword"
    }
    narrowed = ContextRequest.model_validate(
        {**request.model_dump(), "keywords_all": [{"text": "storage"}]}
    )
    assert select(hidden_keyword, profile, narrowed, [topic])["matched"] == []


def test_topic_expansion_is_explicit_and_readable() -> None:
    records, profile, request, topic_id = fixture()
    child = node(
        "narrower",
        SKOS + "Concept",
        **{
            SKOS + "inScheme": [profile.topic_scheme],
            SKOS + "broader": [topic_id],
        },
    )
    solar = records["urn:test:Solar"]
    statement = edge("solar-topic", solar, SUBJECT, child)
    extended = {**records, child.id: child, statement.id: statement}
    assert "urn:test:Solar" not in str(select(extended, profile, request, [topic_id])["matched"])
    expanded = profile.model_copy(update={"topic_expand": "narrower"})
    # A shortcut property on a Concept cannot grant an independently protected relationship.
    assert "urn:test:Solar" not in str(select(extended, expanded, request, [topic_id])["matched"])
    broader = edge("narrower-broader", child, SKOS + "broader", records[topic_id])
    extended[broader.id] = broader
    assert "urn:test:Solar" in str(select(extended, expanded, request, [topic_id])["matched"])
    assert "urn:test:Solar" not in str(
        select({**records, statement.id: statement}, expanded, request, [topic_id])["matched"]
    )
    for unavailable in [broader.id, child.id, topic_id]:
        restricted = {key: value for key, value in extended.items() if key != unavailable}
        assert "urn:test:Solar" not in str(
            select(restricted, expanded, request, [topic_id])["matched"]
        )
    inactive = edge("narrower-broader", child, SKOS + "broader", records[topic_id], active=False)
    assert "urn:test:Solar" not in str(
        select({**extended, inactive.id: inactive}, expanded, request, [topic_id])["matched"]
    )
    wrong_direction = edge("narrower-broader", records[topic_id], SKOS + "broader", child)
    assert "urn:test:Solar" not in str(
        select({**extended, wrong_direction.id: wrong_direction}, expanded, request, [topic_id])[
            "matched"
        ]
    )
    result = select(extended, expanded, request, [topic_id])
    solar_match = next(item for item in result["matched"] if item["node_id"] == solar.id)
    assert {broader.id, child.id, statement.id, topic_id} <= set(solar_match["_dependencies"])
    assert broader.id not in result["_dependencies"]


def test_deadline_and_aggregate_bounds_fail_without_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, profile, request, topic = fixture()
    with pytest.raises(ContextError) as timeout:
        select_context(
            records, "urn:test:Tesla", [topic], profile, request, deadline=time.monotonic() - 1
        )
    assert timeout.value.status == 503
    monkeypatch.setattr("c1.context.select.NODE_LIMIT", 5)
    with pytest.raises(ContextError) as bounds:
        select(records, profile, request, [topic])
    assert bounds.value.status == 422
    monkeypatch.setattr("c1.context.select.NODE_LIMIT", 500)
    monkeypatch.setattr("c1.context.select.EDGE_LIMIT", 3)
    with pytest.raises(ContextError) as bounds:
        select(records, profile, request, [topic])
    assert bounds.value.status == 422


def test_untyped_candidates_do_not_consume_typed_path_limits() -> None:
    records, profile, request, topic = fixture()
    anchor = records["urn:test:Tesla"]
    for index in range(501):
        wrong = node(f"untyped-{index}")
        assertion = edge(f"untyped-edge-{index}", anchor, B + "hasProduct", wrong)
        records[wrong.id], records[assertion.id] = wrong, assertion
    assert len(select(records, profile, request, [topic])["matched"]) == 2


def test_actual_hard_node_and_edge_limits_are_enforced() -> None:
    records, profile, request, topic = fixture()
    anchor = records["urn:test:Tesla"]
    for index in range(500):
        product = node(f"product-{index}", B + "Product")
        assertion = edge(f"product-edge-{index}", anchor, B + "hasProduct", product)
        records[product.id], records[assertion.id] = product, assertion
    with pytest.raises(ContextError, match="traversal_bounds"):
        select(records, profile, request, [topic])
    records, profile, request, topic = fixture()
    product = records["urn:test:Megapack"]
    for index in range(2001):
        assertion = edge(f"parallel-{index}", anchor, B + "hasProduct", product)
        records[assertion.id] = assertion
    with pytest.raises(ContextError, match="traversal_bounds"):
        select(records, profile, request, [topic])


def test_topic_expansion_refuses_descendants_beyond_depth_bound() -> None:
    records, profile, request, topic_id = fixture()
    parent = records[topic_id]
    for index in range(4):
        child = node(
            f"child-{index}",
            SKOS + "Concept",
            **{
                SKOS + "inScheme": [profile.topic_scheme],
            },
        )
        records[child.id] = child
        broader = edge(f"child-broader-{index}", child, SKOS + "broader", parent)
        records[broader.id] = broader
        parent = child
    with pytest.raises(ContextError, match="traversal_bounds"):
        select(
            records, profile.model_copy(update={"topic_expand": "narrower"}), request, [topic_id]
        )


def test_matching_dependencies_include_only_readable_used_resources() -> None:
    records, profile, request, topic = fixture()
    narrowed = ContextRequest.model_validate(
        {**request.model_dump(), "keywords_all": [{"text": "storage"}]}
    )
    result = select(records, profile, narrowed, [topic])
    assert result["_dependencies"] == sorted(["urn:test:Tesla", topic, profile.topic_scheme])
    dependencies = result["matched"][0]["_dependencies"]
    assert {
        "urn:test:storage-keyword",
        "urn:test:vtopic",
        "urn:test:M-B3",
        "urn:test:ap",
        "urn:test:pb",
        "urn:test:bv",
    } <= set(dependencies)
    assert "urn:test:prefix-topic" not in dependencies
    assert "urn:test:TSLA" not in dependencies
    assert "urn:test:Solar" not in dependencies
    no_keywords = select(records, profile, request, [topic])
    assert all(
        "urn:test:storage-keyword" not in item["_dependencies"] for item in no_keywords["matched"]
    )
