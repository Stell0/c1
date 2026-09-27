"""Publication confirmation compares RDF terms as sets without changing literals."""

from __future__ import annotations

from copy import deepcopy

import pytest

from c1.authorization.operations import SecurityOperations
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord

_C1 = "urn:c1:ns:core#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_LANG = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
_ID = "urn:c1:probe:entity/one"
_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
_RELATED = _C1 + "related"
_VALUE = _C1 + "value"


def _record() -> NodeRecord:
    return NodeRecord(
        id=_ID,
        types=[_C1 + "Entity", _C1 + "AdditionalType"],
        properties={
            _LABEL: [
                LiteralValue(lexical="Battery", datatype=_LANG, language="en"),
                LiteralValue(lexical="Akku", datatype=_LANG, language="de"),
            ],
            _RELATED: ["urn:c1:probe:entity/two", "urn:c1:probe:entity/three"],
            _VALUE: [LiteralValue(lexical="+001", datatype=_XSD + "integer")],
        },
    )


def test_confirmation_accepts_reordered_rdf_sets_and_empty_property() -> None:
    expected = _record()
    stored_properties = {key: list(reversed(values)) for key, values in expected.properties.items()}
    stored_properties[_RELATED].append(stored_properties[_RELATED][0])
    stored_properties[_C1 + "unused"] = []
    stored = NodeRecord(
        id=expected.id,
        types=list(reversed(expected.types)),
        properties=stored_properties,
    )

    assert expected != stored  # Pydantic list equality is intentionally order-sensitive.
    assert SecurityOperations._matches(stored, expected)
    assert SecurityOperations._matches(expected, stored)


def test_confirmation_rejects_missing_record_property_or_value() -> None:
    expected = _record()
    without_property = deepcopy(expected.properties)
    del without_property[_RELATED]
    without_value = deepcopy(expected.properties)
    without_value[_RELATED].pop()

    assert not SecurityOperations._matches(None, expected)
    assert not SecurityOperations._matches(
        NodeRecord(id=_ID, types=expected.types, properties=without_property), expected
    )
    assert not SecurityOperations._matches(
        NodeRecord(id=_ID, types=expected.types, properties=without_value), expected
    )


@pytest.mark.parametrize(
    "replacement",
    [
        LiteralValue(lexical="battery", datatype=_LANG, language="en"),
        LiteralValue(lexical="Battery", datatype=_LANG, language="fr"),
        LiteralValue(lexical="Battery", datatype=_XSD + "string"),
    ],
)
def test_confirmation_preserves_literal_text_language_and_datatype(
    replacement: LiteralValue,
) -> None:
    expected = _record()
    changed = deepcopy(expected.properties)
    changed[_LABEL][0] = replacement

    assert not SecurityOperations._matches(
        NodeRecord(id=_ID, types=expected.types, properties=changed), expected
    )


def test_confirmation_preserves_numeric_lexical_spelling() -> None:
    expected = _record()
    changed = deepcopy(expected.properties)
    changed[_VALUE] = [LiteralValue(lexical="1", datatype=_XSD + "integer")]

    assert not SecurityOperations._matches(
        NodeRecord(id=_ID, types=expected.types, properties=changed), expected
    )


def test_confirmation_rejects_changed_id_or_type_set() -> None:
    expected = _record()

    assert not SecurityOperations._matches(
        NodeRecord(
            id="urn:c1:probe:entity/other",
            types=expected.types,
            properties=expected.properties,
        ),
        expected,
    )
    assert not SecurityOperations._matches(
        NodeRecord(id=_ID, types=[_C1 + "Entity"], properties=expected.properties), expected
    )
