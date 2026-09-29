"""Evidence integrity and security negatives for authorized context units."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from c1.context.errors import ContextError
from c1.context.profiles import ContextProfileCatalog
from c1.context.units import MAX_UNITS, build_units
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import (
    ClassDefinition,
    ProfileDefinition,
    ProfileRegistry,
    PropertyDefinition,
)
from c1.model.records import (
    C1,
    DCTERMS,
    OA,
    ActivityRecord,
    AssertionRecord,
    DocumentPartRecord,
    DocumentRecord,
    EntityRecord,
    EvidenceRecord,
    SourceRecord,
)
from c1.query.service import TIME, AuthorizedRecords

B = "urn:c1:ns:batteries#"
BASE = "urn:c1:instance:test:"
XSD = "http://www.w3.org/2001/XMLSchema#"


def lit(text: str, datatype: str = XSD_STRING) -> LiteralValue:
    return LiteralValue(lexical=text, datatype=datatype)


def claim(
    name: str, subject: str, predicate: str, value: str | LiteralValue, **kwargs: Any
) -> NodeRecord:
    return AssertionRecord(
        id=BASE + name,
        subject=subject,
        predicate=predicate,
        object=value,
        origin="manual",
        manual_statement=True,
        attributed_to=BASE + "author",
        **kwargs,
    ).to_node()


def fixture() -> tuple[dict[str, NodeRecord], ProfileRegistry]:
    registry = ProfileRegistry()
    for name, single in (
        ("capacity", True),
        ("energyDensity", True),
        ("unit", True),
        ("conditions", True),
        ("measuredOn", True),
        ("measurementRef", True),
        ("hasVersion", False),
    ):
        registry.predicates[B + name] = PropertyDefinition(
            name, (XSD_STRING,), max_count=1 if single else None
        )
    registry.predicates[DCTERMS + "source"] = PropertyDefinition("source", (C1 + "Source",))
    registry.predicates[B + "measurementRef"] = PropertyDefinition(
        "measurementRef", (B + "Measurement",), max_count=1
    )
    primary_class = ClassDefinition(B + "BatteryVersion", "BatteryVersion", "entity", "hash", {})
    measurement_class = ClassDefinition(B + "Measurement", "Measurement", "entity", "hash", {})
    registry.classes[primary_class.iri] = primary_class
    registry.classes[measurement_class.iri] = measurement_class
    registry.profiles["unit-batteries"] = ProfileDefinition(
        "unit-batteries",
        "1.0.0",
        "0.2.0",
        B + "context",
        {item.iri: item for item in (primary_class, measurement_class)},
        {
            predicate: definition
            for predicate, definition in registry.predicates.items()
            if predicate.startswith(B)
        },
    )
    node = EntityRecord(
        id=BASE + "battery", types=[primary_class.iri], labels=[lit("Battery")]
    ).to_node()
    quantity = claim("quantity", node.id, B + "capacity", lit("3.9", XSD + "decimal"))
    measurement = EntityRecord(
        id=BASE + "measurement", types=[B + "Measurement"], labels=[lit("Measured capacity")]
    ).to_node()
    link = claim("measurement-link", quantity.id, B + "measurementRef", measurement.id)
    unit = claim("unit", measurement.id, B + "unit", lit("MWh"))
    conditions = claim("conditions", measurement.id, B + "conditions", lit("specified conditions"))
    source = SourceRecord(
        id=BASE + "source", title=lit("Datasheet"), kind="synthetic", revision="source-r2"
    ).to_node()
    evidence = EvidenceRecord(
        id=BASE + "evidence",
        assertion_id=quantity.id,
        source_id=source.id,
        source_revision="source-r1",
        excerpt=lit("Synthetic 3.9 MWh"),
        activity_id=BASE + "import",
    ).to_node()
    activity = ActivityRecord(
        id=BASE + "import",
        actor=BASE + "producer",
        used=[source.id],
        outputs=[evidence.id],
        method="deterministic-import",
    ).to_node()
    nodes = [node, quantity, measurement, link, unit, conditions, source, evidence, activity]
    return {item.id: item for item in nodes}, registry


def build(
    records: dict[str, NodeRecord],
    registry: ProfileRegistry,
    *,
    hidden_bounds: dict[str, frozenset[str]] | None = None,
) -> list[dict[str, Any]]:
    profile = ContextProfileCatalog().get("graph-context", "1")
    return build_units(
        AuthorizedRecords(records, hidden_bounds or {}),
        {"matched": [{"node_id": BASE + "battery", "distance": 2, "path": []}]},
        profile,
        registry,
        deadline=time.monotonic() + 20,
    )


def interval(
    records: dict[str, NodeRecord],
    assertion_name: str,
    *,
    unknown: bool = False,
    start: str = "2020-01-01T00:00:00Z",
    end: str = "2030-01-01T00:00:00Z",
) -> None:
    interval_id = BASE + assertion_name + "-interval"
    boundaries = []
    for name, value in (("start", start), ("end", end)):
        properties: dict[str, list[str | LiteralValue]] = {
            C1 + "boundaryState": [lit("unknown" if unknown else "known")]
        }
        if not unknown:
            properties[TIME + "inXSDDateTimeStamp"] = [lit(value, XSD + "dateTimeStamp")]
        boundaries.append(
            NodeRecord(
                id=interval_id + "-" + name, types=[C1 + "TimeBoundary"], properties=properties
            )
        )
    node = NodeRecord(
        id=interval_id,
        types=[C1 + "TimeInterval"],
        properties={TIME + "hasBeginning": [boundaries[0].id], TIME + "hasEnd": [boundaries[1].id]},
    )
    for item in [node, *boundaries]:
        records[item.id] = item
    assertion = records[BASE + assertion_name]
    records[assertion.id] = assertion.model_copy(
        update={"properties": {**assertion.properties, C1 + "validDuring": [node.id]}}
    )


def second_claim(records: dict[str, NodeRecord], *, same_conditions: bool = True) -> None:
    quantity = claim("quantity2", BASE + "battery", B + "capacity", lit("3.6", XSD + "decimal"))
    measurement = EntityRecord(
        id=BASE + "measurement2", types=[B + "Measurement"], labels=[lit("Second measurement")]
    ).to_node()
    nodes = [
        quantity,
        measurement,
        claim("link2", quantity.id, B + "measurementRef", measurement.id),
        claim("unit2", measurement.id, B + "unit", lit("MWh")),
        claim(
            "conditions2",
            measurement.id,
            B + "conditions",
            lit("specified conditions" if same_conditions else "different conditions"),
        ),
    ]
    for node in nodes:
        records[node.id] = node


def test_literal_measurement_and_independently_authorized_qualifiers() -> None:
    records, registry = fixture()
    unit = build(records, registry)[0]
    fact = unit["claims"][0]
    assert fact["value"] == {"kind": "literal", "lexical": "3.9", "datatype": XSD + "decimal"}
    assert fact["measurement_id"] == BASE + "measurement"
    assert fact["measurement_link_assertion_id"] == BASE + "measurement-link"
    assert {item["assertion_id"] for item in fact["qualifiers"]} == {
        BASE + "unit",
        BASE + "conditions",
    }
    assert fact["incomplete"] == []
    assert unit["sources"] == 1 and unit["imports"] == 1
    assert fact["valid_time"]["start"]["state"] == "unknown"
    assert json.loads(json.dumps(unit)) == unit


def test_hidden_qualifier_and_unlinked_same_battery_measurement_do_not_supply_unit() -> None:
    records, registry = fixture()
    del records[BASE + "unit"]
    unrelated = claim("unrelated-unit", BASE + "battery", B + "unit", lit("SECRET"))
    records[unrelated.id] = unrelated
    capacity = next(
        item for item in build(records, registry) if item["predicate"] == B + "capacity"
    )
    assert capacity["claims"][0]["incomplete"] == ["unit"]
    assert "SECRET" not in json.dumps(capacity)


@pytest.mark.parametrize("missing", ["source", "evidence", "measurement-link"])
def test_hidden_dependency_is_absent_without_protected_placeholders(missing: str) -> None:
    records, registry = fixture()
    del records[BASE + missing]
    unit = build(records, registry)[0]
    assert BASE + missing not in json.dumps(unit)
    if missing in {"source", "evidence"}:
        assert unit["claims"][0]["citations"] == []
        assert unit["sources"] == 0
    else:
        assert unit["claims"][0]["incomplete"] == ["unit", "conditions"]


def test_multiple_measurement_links_are_ambiguous_and_never_select_one() -> None:
    records, registry = fixture()
    measurement = EntityRecord(
        id=BASE + "other-measurement", types=[B + "Measurement"], labels=[lit("Other")]
    ).to_node()
    link = claim("other-link", BASE + "quantity", B + "measurementRef", measurement.id)
    records.update({measurement.id: measurement, link.id: link})
    fact = build(records, registry)[0]["claims"][0]
    assert fact["measurement_status"] == "ambiguous"
    assert "measurement_id" not in fact
    assert fact["qualifiers"] == [] and fact["incomplete"] == ["unit", "conditions"]


@pytest.mark.parametrize("types", [[C1 + "Entity"], [B + "UnregisteredMeasurement"]])
def test_measurement_link_with_wrong_target_class_cannot_supply_qualifiers(
    types: list[str],
) -> None:
    records, registry = fixture()
    measurement = records[BASE + "measurement"]
    records[measurement.id] = measurement.model_copy(update={"types": types})
    unit = build(records, registry)[0]
    fact = unit["claims"][0]
    assert "measurement_id" not in fact and "measurement_link_assertion_id" not in fact
    assert fact["qualifiers"] == [] and fact["incomplete"] == ["unit", "conditions"]
    assert all(
        BASE + name not in unit["_dependencies"]
        for name in ("measurement", "measurement-link", "unit", "conditions")
    )


@pytest.mark.parametrize(
    ("unknown", "same_conditions", "comparison"),
    [(False, True, "disagreement"), (True, True, "unresolved"), (False, False, "unresolved")],
)
def test_declared_conflict_requires_known_overlap_and_comparable_qualifiers(
    unknown: bool,
    same_conditions: bool,
    comparison: str,
) -> None:
    records, registry = fixture()
    second_claim(records, same_conditions=same_conditions)
    interval(records, "quantity")
    interval(records, "quantity2", unknown=unknown)
    unit = build(records, registry)[0]
    assert len(unit["claims"]) == 2 and unit["comparison"] == comparison
    assert unit["disagreement"]["declared_conflict"] is (comparison == "disagreement")
    assert BASE + "quantity-start" not in json.dumps(unit)


def test_multi_valued_relationships_and_disjoint_times_are_not_declared_conflicts() -> None:
    records, registry = fixture()
    second_claim(records)
    interval(records, "quantity", end="2022-01-01T00:00:00Z")
    interval(records, "quantity2", start="2023-01-01T00:00:00Z")
    assert build(records, registry)[0]["comparison"] == "unresolved"
    registry.predicates[B + "capacity"] = PropertyDefinition("capacity", (XSD_STRING,))
    unit = build(records, registry)[0]
    assert unit["comparison"] == "multiple_values"
    assert unit["disagreement"]["declared_conflict"] is False


def test_duplicate_imports_and_source_revisions_are_not_independent_sources() -> None:
    records, registry = fixture()
    evidence = EvidenceRecord(
        id=BASE + "evidence2",
        assertion_id=BASE + "quantity",
        source_id=BASE + "source",
        source_revision="source-r2",
        activity_id=BASE + "import2",
    ).to_node()
    activity = ActivityRecord(
        id=BASE + "import2", actor=BASE + "producer", used=[BASE + "source"], outputs=[evidence.id]
    ).to_node()
    automatic = ActivityRecord(
        id=BASE + "automatic-apply", actor=BASE + "server", outputs=[BASE + "evidence"]
    ).to_node()
    records.update({item.id: item for item in [evidence, activity, automatic]})
    unit = build(records, registry)[0]
    assert unit["sources"] == 1 and unit["imports"] == 2
    assert unit["source_versions"] == [
        {"source_id": BASE + "source", "revisions": ["source-r1", "source-r2"]}
    ]
    assert all(
        item["corroboration"] == "duplicate_import" for item in unit["claims"][0]["citations"]
    )
    assert BASE + "automatic-apply" not in json.dumps(unit)


def part_fixture() -> tuple[dict[str, NodeRecord], ProfileRegistry]:
    records, registry = fixture()
    document = DocumentRecord(
        id=BASE + "doc", title=lit("Document"), source_revision="doc-r3"
    ).to_node()
    part = DocumentPartRecord(
        id=BASE + "part",
        document_id=document.id,
        order_key="A1",
        text="préfix 🔋 Battery = 3.9;\n",
        kind="code:python",
    ).to_node()
    selector = NodeRecord(
        id=BASE + "selector",
        types=[C1 + "Selector"],
        properties={
            C1 + "selectorKind": [lit("TextPositionSelector")],
            OA + "start": [lit("7", XSD + "integer")],
            OA + "end": [lit("24", XSD + "integer")],
            B + "secret": [lit("UNDECLARED")],
        },
    )
    source_link = claim("source-link", document.id, DCTERMS + "source", BASE + "source")
    evidence = EvidenceRecord(
        id=BASE + "evidence",
        assertion_id=BASE + "quantity",
        source_id=part.id,
        source_revision="doc-r3",
        selector_id=selector.id,
    ).to_node()
    records.update({item.id: item for item in [document, part, selector, source_link, evidence]})
    return records, registry


def test_part_citation_requires_complete_source_chain_and_exact_codepoint_selector() -> None:
    records, registry = part_fixture()
    citation = build(records, registry)[0]["claims"][0]["citations"][0]
    assert citation["source_id"] == BASE + "source" and citation["document_id"] == BASE + "doc"
    assert citation["evidence_target_id"] == citation["part_id"] == BASE + "part"
    assert citation["source_revision"] == "source-r2"
    assert citation["evidence_source_revision"] == "doc-r3"
    assert build(records, registry)[0]["source_versions"] == [
        {"source_id": BASE + "source", "revisions": ["source-r2"]}
    ]
    assert citation["excerpt"] == "préfix 🔋 Battery = 3.9;\n"[7:24]
    assert citation["excerpt_kind"] == "code" and "UNDECLARED" not in json.dumps(citation)
    dependencies = build(records, registry)[0]["_dependencies"]
    assert all(BASE + name in dependencies for name in ("part", "doc", "selector", "source-link"))


@pytest.mark.parametrize("producer_excerpt", [False, True])
def test_document_and_part_edits_cannot_reuse_evidence_for_an_older_source_revision(
    producer_excerpt: bool,
) -> None:
    records, registry = part_fixture()
    assert len(build(records, registry)[0]["claims"][0]["citations"]) == 1
    document = records[BASE + "doc"]
    records[document.id] = document.model_copy(
        update={"properties": {**document.properties, C1 + "sourceRevision": [lit("doc-r4")]}}
    )
    part = records[BASE + "part"]
    records[part.id] = part.model_copy(
        update={"properties": {**part.properties, C1 + "text": [lit("préfix 🔋 Battery = 9.9;\n")]}}
    )
    if producer_excerpt:
        evidence = records[BASE + "evidence"]
        records[evidence.id] = evidence.model_copy(
            update={
                "properties": {**evidence.properties, C1 + "excerpt": [lit("Old producer excerpt")]}
            }
        )
    unit = build(records, registry)[0]
    assert unit["claims"][0]["citations"] == []
    assert unit["sources"] == 0
    assert "9.9" not in json.dumps(unit) and "Old producer excerpt" not in json.dumps(unit)


def test_part_citation_with_unresolved_document_revision_fails_closed() -> None:
    records, registry = part_fixture()
    document = records[BASE + "doc"]
    records[document.id] = document.model_copy(
        update={
            "properties": {
                predicate: values
                for predicate, values in document.properties.items()
                if predicate != C1 + "sourceRevision"
            }
        }
    )
    assert build(records, registry)[0]["claims"][0]["citations"] == []


@pytest.mark.parametrize("missing", ["doc", "part", "source-link", "source"])
def test_hidden_part_source_chain_cannot_be_bypassed_by_producer_excerpt(missing: str) -> None:
    records, registry = part_fixture()
    evidence = records[BASE + "evidence"]
    records[evidence.id] = evidence.model_copy(
        update={"properties": {**evidence.properties, C1 + "excerpt": [lit("AUTHORED EXCERPT")]}}
    )
    del records[BASE + missing]
    unit = build(records, registry)[0]
    assert unit["claims"][0]["citations"] == []
    assert "AUTHORED EXCERPT" not in json.dumps(unit)


def test_hidden_selector_is_not_rendered_and_excerpt_bounds_preserve_utf8() -> None:
    records, registry = part_fixture()
    del records[BASE + "selector"]
    citation = build(records, registry)[0]["claims"][0]["citations"][0]
    assert "selector" not in citation and "excerpt" not in citation
    evidence = records[BASE + "evidence"]
    records[evidence.id] = evidence.model_copy(
        update={"properties": {**evidence.properties, C1 + "excerpt": [lit("🔋" * 1100)]}}
    )
    citation = build(records, registry)[0]["claims"][0]["citations"][0]
    assert citation["excerpt"] == "🔋" * 1024 and citation["excerpt_truncated"] is True


def test_hidden_temporal_boundary_stays_unknown_and_cannot_prove_overlap() -> None:
    records, registry = fixture()
    interval(records, "quantity")
    node_id = BASE + "quantity-interval"
    records[node_id] = records[node_id].model_copy(
        update={"properties": {TIME + "hasEnd": [node_id + "-end"]}}
    )
    del records[node_id + "-start"]
    unit = build(records, registry, hidden_bounds={node_id: frozenset({TIME + "hasBeginning"})})[0]
    assert unit["claims"][0]["valid_time"]["start"] == {"state": "unknown"}
    assert unit["claims"][0]["valid_time"]["end"]["precision"] == "dateTimeStamp"


def test_input_order_does_not_change_units_and_hidden_relationship_target_is_omitted() -> None:
    records, registry = fixture()
    hidden = claim("hidden-target-claim", BASE + "battery", B + "hasVersion", BASE + "HIDDEN")
    records[hidden.id] = hidden
    assert build(records, registry) == build(dict(reversed(list(records.items()))), registry)
    assert "HIDDEN" not in json.dumps(build(records, registry))


def test_unrelated_installed_profile_cannot_supply_declared_facts() -> None:
    records, registry = fixture()
    baseline = build(records, registry)
    predicate = "urn:unrelated:privateFact"
    registry.predicates[predicate] = PropertyDefinition("privateFact", (XSD_STRING,))
    assertion = claim("unrelated-profile-claim", BASE + "battery", predicate, lit("UNRELATED"))
    records[assertion.id] = assertion
    assert build(records, registry) == baseline


def test_match_dependencies_retain_authorized_relevance_links_for_continuation() -> None:
    records, registry = fixture()
    topic = EntityRecord(id=BASE + "topic", labels=[lit("Battery topic")]).to_node()
    carrier = claim("topic-carrier", BASE + "battery", DCTERMS + "subject", topic.id)
    records.update({item.id: item for item in (topic, carrier)})
    selection = {
        "matched": [
            {
                "node_id": BASE + "battery",
                "distance": 2,
                "path": [],
                "_dependencies": [topic.id, carrier.id, BASE + "withheld"],
            }
        ]
    }
    units = build_units(
        AuthorizedRecords(records, {}),
        selection,
        ContextProfileCatalog().get("graph-context", "1"),
        registry,
        deadline=time.monotonic() + 20,
    )
    assert all(
        topic.id in unit["_dependencies"] and carrier.id in unit["_dependencies"] for unit in units
    )
    assert BASE + "withheld" not in json.dumps(units)


def test_roles_keep_products_and_versions_on_their_own_authorized_paths() -> None:
    records, registry = fixture()
    anchor = EntityRecord(id=BASE + "anchor", labels=[lit("Product named Version")]).to_node()
    product_a = EntityRecord(
        id=BASE + "product-a", types=[B + "Product"], labels=[lit("Product A")]
    ).to_node()
    product_b = EntityRecord(
        id=BASE + "product-b", types=[B + "Product"], labels=[lit("Product B")]
    ).to_node()
    version_b = EntityRecord(
        id=BASE + "battery-b", types=[B + "BatteryVersion"], labels=[lit("Version B")]
    ).to_node()
    nodes = [
        anchor,
        product_a,
        product_b,
        version_b,
        claim("quantity-b", version_b.id, B + "capacity", lit("3.6", XSD + "decimal")),
        claim("anchor-a", anchor.id, B + "hasProduct", product_a.id),
        # The second step follows an incoming assertion; role order must
        # still follow the selected path rather than RDF subject order.
        claim("a-version", BASE + "battery", B + "hasComponent", product_a.id),
        claim("anchor-b", anchor.id, B + "hasProduct", product_b.id),
        claim("b-version", product_b.id, B + "hasComponent", version_b.id),
    ]
    records.update({node.id: node for node in nodes})
    selection = {
        "matched": [
            {
                "node_id": BASE + "battery",
                "distance": 2,
                "path": [BASE + "anchor-a", BASE + "a-version"],
            },
            {
                "node_id": version_b.id,
                "distance": 2,
                "path": [BASE + "anchor-b", BASE + "b-version"],
            },
        ]
    }
    profile = ContextProfileCatalog().get("graph-context", "1")
    profile = profile.model_copy(
        update={
            "role_types": {
                **profile.role_types,
                "path_members": [B + "Product", B + "BatteryVersion"],
            }
        }
    )
    units = build_units(
        AuthorizedRecords(records, {}), selection, profile, registry, deadline=time.monotonic() + 20
    )
    by_node = {unit["node_id"]: unit for unit in units}
    for version_id, product, label in (
        (BASE + "battery", product_a, "Product A"),
        (version_b.id, product_b, "Product B"),
    ):
        roles = by_node[version_id]["roles"]
        assert roles["product"] == [
            {
                "id": product.id,
                "label": label,
                "types": [B + "Product"],
            }
        ]
        assert [item["id"] for item in roles["version"]] == [version_id]
        assert [item["id"] for item in roles["path_members"]] == [product.id, version_id]
        assert anchor.id not in json.dumps(roles)
        assert product.id in by_node[version_id]["_dependencies"]
    # A protected product cannot leave role labels or IDs in the projection.
    del records[product_a.id]
    units = build_units(
        AuthorizedRecords(records, {}), selection, profile, registry, deadline=time.monotonic() + 20
    )
    hidden_roles = next(unit["roles"] for unit in units if unit["node_id"] == BASE + "battery")
    assert hidden_roles["product"] == []
    assert [item["id"] for item in hidden_roles["version"]] == [BASE + "battery"]


def test_import_attribution_ignores_explicitly_inconsistent_activity_links() -> None:
    records, registry = fixture()
    other_source = SourceRecord(
        id=BASE + "other-source", title=lit("Other source"), kind="synthetic"
    ).to_node()
    activity = ActivityRecord(
        id=BASE + "import",
        actor=BASE + "producer",
        used=[other_source.id],
        outputs=[BASE + "evidence"],
    ).to_node()
    records.update({item.id: item for item in [other_source, activity]})
    unit = build(records, registry)[0]
    assert unit["imports"] == 0
    assert unit["claims"][0]["citations"][0]["import_activities"] == []
    assert activity.id not in unit["_dependencies"]


def test_review_confidence_and_external_derivation_remain_attributed_metadata() -> None:
    records, registry = fixture()
    quantity = AssertionRecord(
        id=BASE + "quantity",
        subject=BASE + "battery",
        predicate=B + "capacity",
        object=lit("3.9", XSD + "decimal"),
        origin="derived",
        review_state="disputed",
        confidence=lit("0.7", XSD + "decimal"),
        confidence_method="uncalibrated rubric",
        attributed_to=BASE + "producer",
        activity_id=BASE + "import",
    ).to_node()
    records[quantity.id] = quantity
    fact = build(records, registry)[0]["claims"][0]
    assert fact["review_state"] == "disputed" and fact["origin"] == "derived"
    assert fact["confidence"] == {"lexical": "0.7", "datatype": XSD + "decimal"}
    assert fact["confidence_method"] == "uncalibrated rubric"
    assert fact["attribution_kind"] == "externally_authored_derivation"
    assert fact["attributed_to"] == BASE + "producer"
    assert fact["activity"]["id"] == BASE + "import"


def test_unit_and_deadline_limits_fail_explicitly() -> None:
    records, registry = fixture()
    for index in range(MAX_UNITS):
        predicate = BASE + "predicate" + str(index)
        registry.predicates[predicate] = PropertyDefinition("test", (XSD_STRING,))
        registry.profiles["unit-batteries"].predicates[predicate] = registry.predicates[predicate]
        assertion = claim("bounded" + str(index), BASE + "battery", predicate, lit("x"))
        records[assertion.id] = assertion
    with pytest.raises(ContextError) as error:
        build(records, registry)
    assert error.value.code == "C1-CX-012"
    with pytest.raises(ContextError) as error:
        build_units(
            AuthorizedRecords({}, {}),
            {},
            ContextProfileCatalog().get("graph-context", "1"),
            registry,
            deadline=0,
        )
    assert error.value.code == "C1-QY-053"
