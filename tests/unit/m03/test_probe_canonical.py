"""Probe publication journals the same canonical record that storage writes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from c1.authorization.operations import SecurityOperations
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry


def test_probe_returns_canonical_keyword_record_for_publication() -> None:
    core = "urn:c1:ns:core#"
    record = NodeRecord(
        id="urn:c1:probe:keyword/one",
        types=[core + "Keyword"],
        properties={
            core + "keywordText": [
                LiteralValue(lexical="Battery", datatype="http://www.w3.org/2001/XMLSchema#string")
            ]
        },
    )
    operation = cast(
        SecurityOperations,
        SimpleNamespace(
            settings=SimpleNamespace(enable_probe_routes=True), registry=ProfileRegistry()
        ),
    )

    canonical = SecurityOperations._probe(operation, record)

    assert canonical != record
    assert canonical.properties[core + "normalizedKeyword"] == [
        LiteralValue(lexical="battery", datatype="http://www.w3.org/2001/XMLSchema#string")
    ]
    assert canonical.properties[core + "normalizationVersion"]
    assert SecurityOperations._probe(operation, canonical) == canonical
