"""The internal storage client cannot route a caller to another database."""

from __future__ import annotations

import asyncio
import copy
import inspect
from uuid import uuid4

import pytest

from c1.model.diagnostics import ProfileError
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord, ValidatedBatch
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import (
    document_to_record,
    documents_to_records,
    installed_profile_iri,
    record_to_document,
    records_to_documents,
    storage_id,
)
from c1.storage.schema import _assert_authority, generated_core_schema
from c1.storage.terminus import StorageConfig, StorageError, Terminus


def _config(**overrides: str) -> StorageConfig:
    fields = {
        "url": "http://127.0.0.1:16363",
        "password": "private-test-value",
        "organization": "admin",
        "database": "c1_m02_guard",
        "instance_base": "urn:c1:instance:dev:",
        **overrides,
    }
    return StorageConfig(**fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database", "../other"),
        ("database", "other/database"),
        ("database", "other?graph_type=schema"),
        ("organization", "admin/another"),
        ("organization", "admin%2Fother"),
        ("url", "http://127.0.0.1:16363/api/document/admin/other"),
        ("url", "http://user:pass@127.0.0.1:16363"),
    ],
)
def test_config_rejects_routing_injection(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        _config(**{field: value})


def test_database_and_password_are_not_operation_arguments_or_repr() -> None:
    config = _config()
    assert "private-test-value" not in repr(config)
    with pytest.raises(TypeError):
        Terminus("http://127.0.0.1:16363")  # type: ignore[arg-type]
    for method in (
        Terminus.create,
        Terminus.drop,
        Terminus.head,
        Terminus.documents,
        Terminus.get,
        Terminus.install_profile,
        Terminus.add_profile,
        Terminus.write_records,
        Terminus.read_records,
    ):
        signature = inspect.signature(method)
        assert "database" not in signature.parameters
        assert "organization" not in signature.parameters
        assert "url" not in signature.parameters


def test_path_is_bound_to_validated_configuration() -> None:
    client = Terminus(_config())
    assert client._database_path == "admin/c1_m02_guard"
    assert client._document_path == "/api/document/admin/c1_m02_guard"


def test_create_and_drop_reject_non_test_database_before_network() -> None:
    async def run() -> None:
        async with Terminus(_config(database="knowledge")) as client:
            with pytest.raises(StorageError, match="C1-ST-007"):
                await client.create()
            with pytest.raises(StorageError, match="C1-ST-007"):
                await client.drop()

    asyncio.run(run())


def test_canonical_identity_and_literal_lexical_survive_mapping() -> None:
    registry = ProfileRegistry()
    identifier = f"urn:c1:instance:dev:entity/{uuid4()}"
    label = "http://www.w3.org/2004/02/skos/core#prefLabel"
    lifecycle = "urn:c1:ns:core#lifecycle"
    record = NodeRecord(
        id=identifier,
        types=["urn:c1:ns:core#Entity"],
        properties={
            label: [
                LiteralValue(
                    lexical="Äda",
                    datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                    language="DE",
                )
            ],
            lifecycle: [
                LiteralValue(lexical="active", datatype="http://www.w3.org/2001/XMLSchema#string")
            ],
        },
    )
    document = record_to_document(record, registry, "urn:c1:instance:dev:")
    assert document["@id"] == "Entity/" + identifier.rsplit("/", 1)[1]
    assert document["canonical_iri"] == identifier
    assert document_to_record(document, registry) == record
    changed = record.model_copy(
        update={
            "properties": {
                **record.properties,
                label: [
                    LiteralValue(
                        lexical="Ada",
                        datatype="http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
                        language="de",
                    )
                ],
            }
        }
    )
    assert (
        storage_id(changed, registry.primary_class(changed.types), "urn:c1:instance:dev:")
        == (document["@id"])
    )


def test_unindexable_literals_are_explicit_and_lossless() -> None:
    registry = ProfileRegistry()
    boundary = NodeRecord(
        id=f"urn:c1:instance:dev:boundary/{uuid4()}",
        types=["urn:c1:ns:core#TimeBoundary"],
        properties={
            "urn:c1:ns:core#boundaryState": [
                LiteralValue(lexical="known", datatype="http://www.w3.org/2001/XMLSchema#string")
            ],
            "http://www.w3.org/2006/time#inXSDgYear": [
                LiteralValue(lexical="10000", datatype="http://www.w3.org/2001/XMLSchema#gYear")
            ],
        },
    )
    document = record_to_document(boundary, registry, "urn:c1:instance:dev:")
    assert document["inXSDgYear"]["lexical"] == "10000"
    assert document["inXSDgYear"]["projection_status"] == "out_of_backend_date_range"
    assert document_to_record(document, registry) == boundary

    assertion = NodeRecord(
        id=f"urn:c1:instance:dev:assertion/{uuid4()}",
        types=["urn:c1:ns:core#Assertion"],
        properties={
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [
                LiteralValue(lexical="NaN", datatype="http://www.w3.org/2001/XMLSchema#double")
            ]
        },
    )
    mapped = record_to_document(assertion, registry, "urn:c1:instance:dev:")
    assert mapped["object"]["literal"]["projection_status"] == "nonfinite_double"
    assert "value_double" not in mapped["object"]["literal"]
    assert document_to_record(mapped, registry) == assertion
    for lexical in ("1E-4000", "1E4000"):
        edge = assertion.model_copy(
            update={
                "properties": {
                    "http://www.w3.org/1999/02/22-rdf-syntax-ns#object": [
                        LiteralValue(
                            lexical=lexical,
                            datatype="http://www.w3.org/2001/XMLSchema#double",
                        )
                    ]
                }
            }
        )
        projected = record_to_document(edge, registry, "urn:c1:instance:dev:")
        assert projected["object"]["literal"]["lexical"] == lexical
        assert projected["object"]["literal"]["projection_status"] == "out_of_backend_double_range"
        assert "value_double" not in projected["object"]["literal"]
        assert document_to_record(projected, registry) == edge


def test_public_schema_profile_record_is_not_hidden_by_internal_marker_filter() -> None:
    registry = ProfileRegistry()
    props: dict[str, list[str | LiteralValue]] = {
        "urn:c1:ns:core#profileName": [
            LiteralValue(lexical="example", datatype="http://www.w3.org/2001/XMLSchema#string")
        ],
        "urn:c1:ns:core#profileVersion": [
            LiteralValue(lexical="1.0.0", datatype="http://www.w3.org/2001/XMLSchema#string")
        ],
    }
    public = NodeRecord(
        id=f"urn:c1:instance:dev:profile/{uuid4()}",
        types=["urn:c1:ns:core#SchemaProfile"],
        properties=props,
    )
    markers = [
        NodeRecord(id=installed_profile_iri(name), types=public.types, properties=props)
        for name in ("core", "coreV2")
    ]
    documents = [
        record_to_document(record, registry, "urn:c1:instance:dev:")
        for record in (public, *markers)
    ]
    assert documents_to_records(documents, registry, "urn:c1:instance:dev:") == [public]
    assert documents_to_records(
        documents, registry, "urn:c1:instance:dev:", include_metadata=True
    ) == [public, *markers]
    for marker in markers:
        with pytest.raises(StorageError, match="C1-ST-004"):
            records_to_documents([marker], registry, "urn:c1:instance:dev:")

    async def reject_before_network() -> None:
        async with Terminus(_config()) as client:
            for marker in markers:
                with pytest.raises(StorageError, match="C1-ST-004"):
                    await client.write_records(
                        ValidatedBatch(records=[marker]), registry, expected_head="branch:abc"
                    )

    asyncio.run(reject_before_network())


def test_every_core_class_and_declared_field_maps_back_exactly() -> None:
    registry = ProfileRegistry()
    sample = {
        "boolean": "1",
        "integer": "+00042",
        "decimal": "+042.5000",
        "double": "1.25E+03",
        "date": "2020-05-03",
        "dateTime": "2020-05-03T12:00:00",
        "dateTimeStamp": "2020-05-03T12:00:00Z",
        "gYear": "2020",
        "gYearMonth": "2020-05",
        "anyURI": "urn:c1:example:value",
        "string": "Example",
    }
    base = "urn:c1:instance:dev:"
    for class_definition in registry.classes.values():
        properties: dict[str, list[str | LiteralValue]] = {}
        for predicate, definition in class_definition.properties.items():
            if definition.enum:
                value: str | LiteralValue = LiteralValue(
                    lexical=definition.enum[0], datatype="http://www.w3.org/2001/XMLSchema#string"
                )
            elif "@id" in definition.ranges:
                value = f"{base}entity/{uuid4()}"
            elif "http://www.w3.org/2000/01/rdf-schema#Literal" in definition.ranges:
                value = LiteralValue(
                    lexical="42.5000", datatype="http://www.w3.org/2001/XMLSchema#decimal"
                )
            else:
                datatype = definition.ranges[-1]
                lexical = sample.get(datatype.rsplit("#", 1)[-1], "Example")
                language = "en" if datatype.endswith("#langString") else None
                value = LiteralValue(lexical=lexical, datatype=datatype, language=language)
            properties[predicate] = [value]
        kind = class_definition.storage_name.lower()
        identifier = f"{base}{kind}/{uuid4()}"
        record = NodeRecord(id=identifier, types=[class_definition.iri], properties=properties)
        document = record_to_document(record, registry, base)
        assert document_to_record(document, registry) == record, class_definition.storage_name


def test_write_revalidates_manually_constructed_batch_before_network() -> None:
    registry = ProfileRegistry()
    invalid = ValidatedBatch(
        records=[
            NodeRecord(
                id=f"urn:c1:instance:dev:entity/{uuid4()}",
                types=["urn:c1:ns:core#Entity"],
                properties={},
            )
        ]
    )

    async def run() -> None:
        async with Terminus(_config()) as client:
            with pytest.raises(ProfileError, match="C1-IX-030"):
                await client.write_records(invalid, registry, expected_head="branch:abc")

    asyncio.run(run())


def test_installed_schema_field_change_is_rejected_even_with_same_version() -> None:
    registry = ProfileRegistry()
    installed = copy.deepcopy(generated_core_schema(registry))
    entity = next(item for item in installed if item.get("@id") == "Entity")
    entity["label"] = "xsd:string"
    with pytest.raises(StorageError, match="C1-ST-006"):
        _assert_authority(installed, registry)


def test_embedded_literal_lexical_field_change_is_rejected() -> None:
    registry = ProfileRegistry()
    installed = copy.deepcopy(generated_core_schema(registry))
    literal = next(item for item in installed if item.get("@id") == "LiteralValue")
    literal["lexical"] = "xsd:integer"
    with pytest.raises(StorageError, match="embedded value schema differs"):
        _assert_authority(installed, registry)
