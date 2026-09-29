"""Readable exact selectors, redirects and explicit topic schemes."""

from pathlib import Path

import pytest

from c1.context.errors import ContextError
from c1.context.profiles import ContextProfile, load_context_profile
from c1.context.request import IDSelector, LabelSelector
from c1.context.resolve import resolve_anchor
from c1.context.topics import resolve_topics
from c1.model.literals import RDF_LANG_STRING, XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ClassDefinition, ProfileRegistry
from c1.model.records import C1, SKOS

IDENTITY = "urn:c1:ns:identity#"


def profile() -> ContextProfile:
    return load_context_profile(Path("profiles/context/graph-context.json"))


def lit(value: str, language: str | None = None) -> LiteralValue:
    return LiteralValue(
        lexical=value, datatype=RDF_LANG_STRING if language else XSD_STRING, language=language
    )


def entity(name: str, label: str, *, language: str | None = None) -> NodeRecord:
    return NodeRecord(
        id="urn:test:" + name,
        types=[C1 + "Entity"],
        properties={SKOS + "prefLabel": [lit(label, language)]},
    )


def test_anchor_exact_alias_language_ambiguity_and_unresolved() -> None:
    company, other = entity("tesla", "Tesla"), entity("person", "Someone")
    other = other.model_copy(
        update={
            "properties": {
                **other.properties,
                SKOS + "altLabel": [lit("Tesla", "it")],
            }
        }
    )
    records = {node.id: node for node in [company, other]}
    ambiguous = resolve_anchor(records, LabelSelector(label=" ＴＥＳＬＡ "), profile())
    assert ambiguous["outcome"] == "ambiguous"
    assert [item["id"] for item in ambiguous["candidates"]] == sorted(records)
    assert "facts" not in ambiguous
    resolved = resolve_anchor(records, LabelSelector(label="tesla", language="IT"), profile())
    assert resolved["anchor"]["id"] == other.id
    assert resolve_anchor(records, LabelSelector(label="Tes"), profile())["outcome"] == "unresolved"
    # A removed/hidden candidate cannot affect disambiguation.
    assert (
        resolve_anchor({company.id: company}, LabelSelector(label="Tesla"), profile())["outcome"]
        == "resolved"
    )


def test_unknown_hidden_and_wrong_type_ids_share_failure() -> None:
    assertion = NodeRecord(id="urn:test:assertion", types=[C1 + "Assertion"], properties={})
    failures = []
    for identifier in ["urn:test:unknown", "urn:test:hidden", assertion.id]:
        with pytest.raises(ContextError) as error:
            resolve_anchor({assertion.id: assertion}, IDSelector(id=identifier), profile())
        failures.append((error.value.status, error.value.code, str(error.value)))
    assert failures[0] == failures[1] == failures[2]
    assert failures[0][0] == 404


def test_generic_entity_anchor_uses_trusted_primary_class_kind() -> None:
    registry = ProfileRegistry()
    custom = "urn:test:Product"
    registry.classes[custom] = ClassDefinition(
        custom, "Product", "entity", "Random", registry.classes[C1 + "Entity"].properties
    )
    product = entity("product", "Product").model_copy(update={"types": [custom]})
    source = entity("source", "Source").model_copy(update={"types": [C1 + "Source"]})
    records = {product.id: product, source.id: source}
    assert (
        resolve_anchor(records, IDSelector(id=product.id), profile(), registry)["anchor"]["id"]
        == product.id
    )
    with pytest.raises(ContextError):
        resolve_anchor(records, IDSelector(id=source.id), profile(), registry)


def test_redirect_requires_readable_active_decision_and_survivor() -> None:
    old, survivor = entity("old", "Former"), entity("survivor", "Tesla")
    old = old.model_copy(
        update={"properties": {**old.properties, C1 + "lifecycle": [lit("superseded")]}}
    )
    decision = NodeRecord(id="urn:test:decision", types=[C1 + "ResolutionRecord"], properties={})
    redirect = NodeRecord(
        id="urn:test:redirect",
        types=[IDENTITY + "Redirect"],
        properties={
            IDENTITY + "from": [old.id],
            IDENTITY + "to": [survivor.id],
            IDENTITY + "resolution": [decision.id],
            C1 + "lifecycle": [lit("active")],
        },
    )
    records = {node.id: node for node in [old, survivor, decision, redirect]}
    assert resolve_anchor(records, IDSelector(id=old.id), profile())["anchor"]["id"] == survivor.id
    assert resolve_anchor(records, LabelSelector(label="Former"), profile())[
        "_dependencies"
    ] == sorted(records)
    assert (
        resolve_anchor(records, LabelSelector(label="Former"), profile())["anchor"]["id"]
        == survivor.id
    )
    for hidden in [redirect.id, decision.id, survivor.id]:
        with pytest.raises(ContextError):
            resolve_anchor(
                {key: node for key, node in records.items() if key != hidden},
                IDSelector(id=old.id),
                profile(),
            )
    inactive = redirect.model_copy(
        update={
            "properties": {
                **redirect.properties,
                C1 + "lifecycle": [lit("retracted")],
            }
        }
    )
    with pytest.raises(ContextError):
        resolve_anchor({**records, inactive.id: inactive}, IDSelector(id=old.id), profile())


def test_topics_are_scheme_bounded_readable_exact_and_language_aware() -> None:
    chosen = profile()
    scheme = NodeRecord(id=chosen.topic_scheme, types=[SKOS + "ConceptScheme"], properties={})
    topic = NodeRecord(
        id="urn:test:storage",
        types=[SKOS + "Concept"],
        properties={
            SKOS + "prefLabel": [lit("Energy storage", "en")],
            SKOS + "altLabel": [lit("Storage", "en")],
            SKOS + "inScheme": [scheme.id],
        },
    )
    outside = topic.model_copy(
        update={
            "id": "urn:test:outside",
            "properties": {
                **topic.properties,
                SKOS + "inScheme": ["urn:test:other-scheme"],
            },
        }
    )
    records = {node.id: node for node in [scheme, topic, outside]}
    result = resolve_topics(
        records, ["STORAGE", LabelSelector(label="energy storage", language="EN")], chosen
    )
    assert result["outcome"] == "resolved"
    assert result["_dependencies"] == sorted([scheme.id, topic.id])
    assert [item["id"] for item in result["topics"]] == [topic.id]
    assert resolve_topics(records, ["stor"], chosen)["outcome"] == "unresolved"
    assert (
        resolve_topics(records, [LabelSelector(label="storage", language="it")], chosen)["outcome"]
        == "unresolved"
    )
    assert resolve_topics(records, [IDSelector(id=outside.id)], chosen)["outcome"] == "unresolved"
    assert resolve_topics({topic.id: topic}, ["storage"], chosen)["outcome"] == "unresolved"
    second = topic.model_copy(update={"id": "urn:test:second"})
    ambiguous = resolve_topics({**records, second.id: second}, ["storage"], chosen)
    assert ambiguous["outcome"] == "ambiguous"
    assert [item["id"] for item in ambiguous["selectors"][0]["candidates"]] == sorted(
        [topic.id, second.id]
    )
    assert resolve_topics(records, [], chosen) == {
        "outcome": "resolved",
        "topics": [],
        "selectors": [],
        "_dependencies": [],
    }
