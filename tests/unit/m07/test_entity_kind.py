"""Explicit custom entity kinds keep ordinary entity API and identity semantics."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from c1.authorization.principal import Principal
from c1.changes.identity import IdentityPlanError, expand_identity
from c1.changes.models import CreateOperation, SplitOperation
from c1.changes.profiles import load_candidate
from c1.interchange import duplicate_candidates, export_jsonld, import_jsonld, validate_records
from c1.model.diagnostics import ProfileError
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, SKOS, AssertionRecord, EntityRecord
from c1.query.filters import KeywordTerm, LabelFilter, QueryFilters
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords, QueryService
from c1.runtime import Runtime
from c1.storage.mapping import document_to_record, record_to_document

BASE = "urn:c1:instance:dev:"
CONCEPT = SKOS + "Concept"
ROOT = Path(__file__).resolve().parents[3]


def literal(text: str) -> LiteralValue:
    return LiteralValue(lexical=text, datatype=XSD_STRING)


def concept(suffix: str, *, label: str = "Battery") -> NodeRecord:
    return NodeRecord(
        id=BASE + "entity/" + suffix,
        types=[CONCEPT],
        properties={
            SKOS + "prefLabel": [literal(label)],
            SKOS + "altLabel": [literal("Storage")],
            SKOS + "inScheme": [BASE + "entity/scheme"],
            C1 + "lifecycle": [literal("active")],
        },
    )


def registry() -> ProfileRegistry:
    return load_candidate("topics")[0]


@pytest.mark.parametrize("mutation", ["missing", "changed_range", "changed_count", "changed_name"])
def test_entity_kind_requires_unchanged_full_entity_template(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "topics"
    shutil.copytree(ROOT / "profiles/available/topics", path)
    manifest = json.loads((path / "profile.json").read_text())
    properties = manifest["classes"][CONCEPT]["properties"]
    if mutation == "missing":
        del properties[C1 + "keyword"]
    elif mutation == "changed_range":
        properties[C1 + "keyword"]["ranges"] = [XSD_STRING]
    elif mutation == "changed_count":
        properties[C1 + "keyword"]["max_count"] = 1
    else:
        properties[C1 + "keyword"]["name"] = "otherName"
    (path / "profile.json").write_text(json.dumps(manifest))
    with pytest.raises(ProfileError, match="full core Entity template"):
        ProfileRegistry().load(path)


def test_classification_is_explicit_and_requires_one_primary_class() -> None:
    loaded = registry()
    assert loaded.is_entity([CONCEPT])
    assert loaded.is_entity([C1 + "Entity", "urn:test:unregistered-domain-type"])
    assert not loaded.is_entity([CONCEPT, C1 + "Entity"])
    assert not loaded.is_entity([C1 + "Source"])
    assert not loaded.is_entity(["urn:test:unknown"])
    loaded.classes[CONCEPT] = replace(loaded.classes[CONCEPT], kind="record")
    assert not loaded.is_entity([CONCEPT])


def test_entity_kind_rejects_supplemental_constraints_on_core_properties(tmp_path: Path) -> None:
    path = tmp_path / "topics"
    shutil.copytree(ROOT / "profiles/available/topics", path)
    shapes = path / "shapes.ttl"
    shapes.write_text(
        shapes.read_text().replace(
            "sh:minCount 1 ; sh:or", 'sh:minCount 1 ; sh:pattern "^[A-Z]" ; sh:or', 1
        )
    )
    with pytest.raises(ProfileError, match="preserve core Entity SHACL constraints"):
        ProfileRegistry().load(path)


def test_custom_entity_preserves_iri_labels_and_types_in_storage_and_interchange() -> None:
    loaded = registry()
    node = concept("battery").model_copy(
        update={"id": BASE + "entity/00000000-0000-4000-8000-000000000001"}
    )
    assert document_to_record(record_to_document(node, loaded, BASE), loaded) == node
    assert import_jsonld(export_jsonld([node], loaded), loaded).records == [node]
    assert node.types == [CONCEPT]


def test_custom_entity_keywords_coalesce_and_duplicates_use_only_visible_inputs() -> None:
    loaded = registry()
    node = concept("battery")
    keywords = [
        NodeRecord(
            id=BASE + "keyword/" + suffix,
            types=[C1 + "Keyword"],
            properties={
                C1 + "keywordText": [literal(text)],
            },
        )
        for suffix, text in [("one", "Battery"), ("two", "battery")]
    ]
    node = node.model_copy(
        update={
            "properties": {**node.properties, C1 + "keyword": [keyword.id for keyword in keywords]}
        }
    )
    batch = validate_records([node, *keywords], loaded)
    normalized = next(item for item in batch.records if item.id == node.id)
    assert normalized.properties[C1 + "keyword"] == [keywords[0].id]
    assert any(item.code == "C1-IX-041" for item in batch.diagnostics)
    duplicate = concept("duplicate")
    assert duplicate_candidates([duplicate], registry=loaded) == []
    hints = duplicate_candidates([duplicate], [concept("visible")], loaded)
    assert len(hints) == 1 and "visible" in hints[0].message


def query_service(monkeypatch: pytest.MonkeyPatch, nodes: list[NodeRecord]) -> QueryService:
    records = AuthorizedRecords({node.id: node for node in nodes}, {})
    plan = AuthorizedPlan(
        workflow_head="security",
        readable_scopes=frozenset(),
        authorized_ids=tuple(sorted(records)),
        scope_by_id={},
    )
    runtime = cast(
        Runtime,
        SimpleNamespace(
            settings=SimpleNamespace(
                cursor_secret="x" * 32,
                query_candidate_limit=5000,
                max_readable_scopes=500,
                query_time_budget_ms=2000,
                instance_id="test",
            ),
            registry=registry(),
            journal=None,
            fga=None,
            plane=None,
            knowledge=SimpleNamespace(head=AsyncMock(return_value="revision")),
        ),
    )
    service = QueryService(runtime)
    monkeypatch.setattr(service, "selection", AsyncMock(return_value=(plan, {})))
    monkeypatch.setattr(service, "records", AsyncMock(return_value=records))
    monkeypatch.setattr(service.planner, "finalize", AsyncMock())
    return service


def test_custom_entity_lookup_keyword_alias_and_exact_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = registry()
    node = concept("battery")
    keyword = NodeRecord(
        id=BASE + "keyword/one",
        types=[C1 + "Keyword"],
        properties={
            C1 + "keywordText": [literal("Battery")],
        },
    )
    node = node.model_copy(update={"properties": {**node.properties, C1 + "keyword": [keyword.id]}})
    nodes = validate_records([node, keyword], loaded).records
    service = query_service(monkeypatch, nodes)
    principal = Principal("test", "dave", "human")

    async def run() -> None:
        page = await service.entities(
            principal,
            QueryFilters(
                alias=LabelFilter(text="storage"), keywords_all=[KeywordTerm(text="battery")]
            ),
        )
        assert page["count"] == 1 and page["items"][0]["id"] == node.id
        exact_core = await service.entities(principal, QueryFilters(types=[C1 + "Entity"]))
        assert exact_core["count"] == 0
        exact_custom = await service.entities(principal, QueryFilters(types=[CONCEPT]))
        assert exact_custom["count"] == 1
        assert (await service.entity(principal, node.id))["types"] == [CONCEPT]
        with pytest.raises(QueryPlanError, match="not_found"):
            await service.entity(principal, BASE + "entity/hidden")

    asyncio.run(run())


def test_custom_entity_neighborhood_and_export(monkeypatch: pytest.MonkeyPatch) -> None:
    node = concept("battery")
    target = concept("broader", label="Energy")
    edge = AssertionRecord(
        id=BASE + "assertion/link",
        subject=node.id,
        predicate=SKOS + "broader",
        object=target.id,
        origin="manual",
        manual_statement=True,
        attributed_to=BASE + "actor/test",
    ).to_node()
    service = query_service(monkeypatch, [node, target, edge])
    principal = Principal("test", "dave", "human")

    async def run() -> None:
        neighborhood = await service.neighborhood(
            principal, node.id, predicates=frozenset({SKOS + "broader"})
        )
        assert neighborhood["edges"][0]["assertion_id"] == edge.id
        page = await service.export(principal, types=(CONCEPT,))
        assert page["count"] == 2
        assert {item["@id"] for item in page["snapshot"]["@graph"]} == {node.id, target.id}

    asyncio.run(run())


def test_custom_entity_split_keeps_type_and_rejects_nonentities() -> None:
    loaded = registry()
    source = concept("source")

    async def resolve(identifier: str) -> NodeRecord | None:
        return source if identifier == source.id else None

    async def authorize(_identifier: str) -> bool:
        return True

    async def assertions(_identifier: str) -> list[NodeRecord]:
        return []

    async def run() -> None:
        new = concept("new")
        args: dict[str, Any] = {
            "base": BASE,
            "actor": BASE + "actor/test",
            "resolve": resolve,
            "authorize": authorize,
            "list_assertions": assertions,
            "registry": loaded,
        }
        expanded = await expand_identity(
            SplitOperation(
                source_id=source.id,
                new_entity=new.model_dump(mode="json"),
                assertion_plan=[],
                rationale="distinct topics",
                scope_id="shared",
            ),
            **args,
        )
        assert isinstance(expanded[0], CreateOperation)
        assert expanded[0].record["types"] == [CONCEPT]
        invalid = EntityRecord(id=BASE + "entity/invalid", labels=[literal("Invalid")]).to_node()
        invalid = invalid.model_copy(update={"types": [C1 + "Source"]})
        with pytest.raises(IdentityPlanError, match="Invalid split entity"):
            await expand_identity(
                SplitOperation(
                    source_id=source.id,
                    new_entity=invalid.model_dump(mode="json"),
                    assertion_plan=[],
                    rationale="invalid",
                    scope_id="shared",
                ),
                **args,
            )

    asyncio.run(run())
