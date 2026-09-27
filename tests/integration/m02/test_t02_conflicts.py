"""M02-T02: disagreement and multiple relations survive a real commit."""

from __future__ import annotations

import asyncio

from c1.interchange import import_jsonld
from c1.model.literals import LiteralValue
from c1.model.profiles import ProfileRegistry
from tests.integration.m02.conftest import expected, fixture_payload, live_knowledge

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
C1 = "urn:c1:ns:core#"


def test_t02_conflicts_and_multiple_employments_are_separate_assertions() -> None:
    async def run() -> None:
        registry = ProfileRegistry()
        batch = import_jsonld(fixture_payload(), registry)
        identities = expected("identities.json")
        async with live_knowledge(registry) as db:
            before = await db.head()
            await db.write_records(batch, registry, expected_head=before)
            records = {item.id: item for item in await db.read_records(registry)}

            revenue = [records[key] for key in identities["revenue_assertions"]]
            assert revenue[0].id != revenue[1].id
            assert all(
                item.properties[RDF + "subject"] == [identities["tesla"]] for item in revenue
            )
            assert all(item.properties[RDF + "predicate"] == [C1 + "revenue"] for item in revenue)
            assert [item.properties[RDF + "object"][0] for item in revenue] == [
                LiteralValue(
                    lexical="42.5000", datatype="http://www.w3.org/2001/XMLSchema#decimal"
                ),
                LiteralValue(
                    lexical="41.7500", datatype="http://www.w3.org/2001/XMLSchema#decimal"
                ),
            ]
            assert revenue[0].properties[C1 + "evidence"] != revenue[1].properties[C1 + "evidence"]

            employment = [records[key] for key in identities["employment_assertions"]]
            assert employment[0].id != employment[1].id
            assert all(
                item.properties[RDF + "subject"] == [identities["ada"]] for item in employment
            )
            assert all(
                item.properties[RDF + "predicate"] == [C1 + "worksFor"] for item in employment
            )
            assert [item.properties[RDF + "object"] for item in employment] == [
                [identities["tesla"]],
                [identities["battery"]],
            ]

            manual = records[identities["manual_assertion"]]
            assert manual.properties[C1 + "manualStatement"] == [
                LiteralValue(lexical="true", datatype="http://www.w3.org/2001/XMLSchema#boolean")
            ]
            assert "http://www.w3.org/ns/prov#wasAttributedTo" in manual.properties
            assert C1 + "evidence" not in manual.properties

    asyncio.run(run())
