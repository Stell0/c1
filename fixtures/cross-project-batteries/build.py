"""Pure, reproducible synthetic M07 fixture construction (no network or credentials)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

C1 = "urn:c1:ns:core#"
B = "urn:c1:ns:batteries#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PROV = "http://www.w3.org/ns/prov#"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
TIME = "http://www.w3.org/2006/time#"


def identifier(key: str, kind: str = "entity") -> str:
    # The fixture is deterministic, while canonical storage IDs require UUIDv4
    # syntax. Preserve the name-derived bytes and set the required version bits.
    named = uuid.uuid5(uuid.NAMESPACE_URL, "c1-m07/" + key)
    canonical = uuid.UUID(bytes=named.bytes, version=4)
    return f"urn:c1:instance:dev:{kind}/{canonical}"


def text(value: str, datatype: str = "string") -> dict[str, str]:
    return {"lexical": value, "datatype": XSD + datatype}


def build_profile(core: dict[str, Any]) -> dict[str, Any]:
    """Custom entities reuse the supported core Entity properties, one type each."""
    classes = {
        B + name: {
            "storage_name": name,
            "kind": "entity",
            "key_strategy": "Random",
            "properties": core["classes"][C1 + "Entity"]["properties"],
        }
        for name in ("Product", "Battery", "BatteryVersion", "Measurement")
    }
    ranges = {
        "hasProduct": [B + "Product"],
        "hasComponent": [B + "Battery", B + "BatteryVersion"],
        "hasVersion": [B + "BatteryVersion"],
        "hasInstrument": [C1 + "Entity"],
        "capacity": [XSD + "decimal"],
        "energyDensity": [XSD + "decimal"],
        "unit": [XSD + "string"],
        "conditions": [XSD + "string"],
        "measuredOn": [XSD + "date"],
        "cycleLife": [XSD + "integer"],
        "measurementRef": [B + "Measurement"],
    }
    predicates = {
        B + name: {
            "name": name,
            "ranges": values,
            "min_count": 0,
            "max_count": 1 if name in {"capacity", "measurementRef"} else None,
            "enum": [],
        }
        for name, values in ranges.items()
    }
    predicates[DCT + "source"] = {
        "name": "documentSource",
        "ranges": [C1 + "Source"],
        "min_count": 0,
        "max_count": None,
        "enum": [],
    }
    return {
        "name": "batteries",
        "version": "1.0.0",
        "requires_core": "1.0.0",
        "context": "context.jsonld",
        "shapes": "shapes.ttl",
        "classes": classes,
        "predicates": predicates,
    }


def build_fixture() -> dict[str, Any]:
    ids: dict[str, str] = {}
    records: dict[str, list[dict[str, Any]]] = {"papertrader": [], "robotelier": []}

    def node(
        key: str,
        kind: str,
        type_iri: str,
        properties: dict[str, Any],
        scope: str = "bat-robotelier",
        producer: str = "robotelier",
    ) -> str:
        iri = identifier(key, kind)
        ids[key] = iri
        records[producer].append(
            {"id": iri, "types": [type_iri], "properties": properties, "scope": scope}
        )
        return iri

    def entity(key: str, label: str, cls: str = C1 + "Entity", **kw: Any) -> str:
        return node(
            key,
            "entity",
            cls,
            {
                SKOS + "prefLabel": [text(label)],
                C1 + "lifecycle": [text("active")],
            },
            **kw,
        )

    def assertion(
        key: str,
        subject: str,
        predicate: str,
        value: Any,
        *,
        scope: str = "bat-robotelier",
        producer: str = "robotelier",
        evidence: list[str] | None = None,
        interval: str | None = None,
    ) -> str:
        props = {
            RDF + "subject": [subject],
            RDF + "predicate": [predicate],
            RDF + "object": [value],
            C1 + "origin": [text("imported" if evidence else "manual")],
            C1 + "reviewState": [text("reported")],
            C1 + "lifecycle": [text("active")],
            C1 + "manualStatement": [text("false" if evidence else "true", "boolean")],
            PROV + "wasAttributedTo": ["urn:c1:fixture:producer:" + producer],
        }
        if evidence:
            props[C1 + "evidence"] = evidence
        if interval:
            props[C1 + "validDuring"] = [interval]
        return node(key, "assertion", C1 + "Assertion", props, scope, producer)

    tesla = entity("tesla", "Tesla", scope="bat-shared", producer="papertrader")
    instrument = entity(
        "instrument", "TSLA-synthetic", scope="bat-papertrader", producer="papertrader"
    )
    assertion(
        "tesla-instrument",
        tesla,
        B + "hasInstrument",
        instrument,
        scope="bat-papertrader",
        producer="papertrader",
    )
    assertion(
        "revenue",
        tesla,
        C1 + "revenue",
        text("42", "decimal"),
        scope="bat-papertrader",
        producer="papertrader",
    )
    scheme = entity(
        "topic-scheme", "Synthetic M07 topics", scope="bat-shared", producer="papertrader"
    )
    for key, label in (
        ("batteries", "batteries"),
        ("energy-storage", "energy storage"),
        ("vehicles", "vehicles"),
        ("financial-instruments", "financial instruments"),
    ):
        props: dict[str, Any] = {
            SKOS + "prefLabel": [text(label)],
            SKOS + "inScheme": [scheme],
            C1 + "lifecycle": [text("active")],
        }
        if key == "energy-storage":
            props[SKOS + "altLabel"] = [text("storage")]
        node("topic-" + key, "concept", SKOS + "Concept", props, "bat-shared", "papertrader")
    assertion(
        "instrument-topic",
        instrument,
        DCT + "subject",
        ids["topic-financial-instruments"],
        scope="bat-papertrader",
        producer="papertrader",
    )

    topic_source = node(
        "topic-source",
        "source",
        C1 + "Source",
        {
            DCT + "title": [text("Synthetic battery topic declarations")],
            C1 + "sourceKind": [text("synthetic-fixture")],
            C1 + "sourceRevision": [text("source-v1")],
        },
    )
    for key, label in (
        ("optimus", "Optimus-synthetic"),
        ("vehicle", "Vehicle-synthetic"),
        ("megapack", "Megapack-synthetic"),
        ("solar", "Solar-tile-synthetic"),
        ("prototype", "Prototype-synthetic"),
    ):
        scope = "bat-hidden" if key == "prototype" else "bat-robotelier"
        product = entity(key, label, B + "Product", scope=scope)
        assertion("tesla-" + key, tesla, B + "hasProduct", product, scope=scope)
    battery = entity("vehicle-battery", "Vehicle battery-synthetic", B + "Battery")
    assertion("vehicle-component", ids["vehicle"], B + "hasComponent", battery)
    for key, label, parent in (
        ("o-b1", "O-B1", "optimus"),
        ("v-b2", "V-B2", "vehicle-battery"),
        ("m-b3", "M-B3", "megapack"),
        ("p-b4", "P-B4", "prototype"),
    ):
        scope = "bat-hidden" if key == "p-b4" else "bat-robotelier"
        version = entity(key, label, B + "BatteryVersion", scope=scope)
        assertion(
            key + "-path",
            ids[parent],
            B + ("hasVersion" if key == "v-b2" else "hasComponent"),
            version,
            scope=scope,
        )
        for topic in ("batteries", "energy-storage"):
            evidence_id = identifier(key + "-" + topic + "-evidence", "evidence")
            assertion(
                key + "-" + topic,
                version,
                DCT + "subject",
                ids["topic-" + topic],
                scope=scope,
                evidence=[evidence_id],
            )
            node(
                key + "-" + topic + "-evidence",
                "evidence",
                C1 + "Evidence",
                {
                    C1 + "assertionRef": [ids[key + "-" + topic]],
                    OA + "hasSource": [topic_source],
                    C1 + "sourceRevision": [text("source-v1")],
                    C1 + "excerpt": [text(f"{label} has synthetic topic {topic}.")],
                },
                scope,
            )
        keywords = (
            ["batteries", "tesla"]
            if key == "v-b2"
            else (["megapack", "storage"] if key == "m-b3" else [])
        )
        for keyword in keywords:
            kwid = node(
                "keyword-" + key + "-" + keyword,
                "keyword",
                C1 + "Keyword",
                {
                    C1 + "keywordText": [text(keyword)],
                    C1 + "normalizedKeyword": [text(keyword)],
                    C1 + "normalizationVersion": [text("c1-kw-1")],
                },
                scope,
            )
            next(item for item in records["robotelier"] if item["id"] == version)[
                "properties"
            ].setdefault(C1 + "keyword", []).append(kwid)

    start = node(
        "valid-start",
        "time-boundary",
        C1 + "TimeBoundary",
        {
            C1 + "boundaryState": [text("known")],
            TIME + "inXSDDateTimeStamp": [text("2026-01-01T00:00:00Z", "dateTimeStamp")],
        },
    )
    end = node(
        "valid-end",
        "time-boundary",
        C1 + "TimeBoundary",
        {
            C1 + "boundaryState": [text("known")],
            TIME + "inXSDDateTimeStamp": [text("2027-01-01T00:00:00Z", "dateTimeStamp")],
        },
    )
    interval = node(
        "valid-interval",
        "time-interval",
        C1 + "TimeInterval",
        {
            TIME + "hasBeginning": [start],
            TIME + "hasEnd": [end],
        },
    )
    for key, title in (
        ("o-source", "O-B1 synthetic datasheet"),
        ("m-source-a", "M-B3 synthetic manufacturer datasheet"),
        ("m-source-b", "M-B3 synthetic laboratory report"),
        ("v-source", "V-B2 synthetic datasheet"),
        ("p-source", "Hidden prototype synthetic report"),
    ):
        node(
            key,
            "source",
            C1 + "Source",
            {
                DCT + "title": [text(title)],
                C1 + "sourceKind": [text("synthetic-datasheet")],
                C1 + "sourceRevision": [text("source-v1")],
            },
            "bat-hidden" if key == "p-source" else "bat-robotelier",
        )
    document = node(
        "datasheet",
        "document",
        C1 + "Document",
        {
            DCT + "title": [text("M-B3 synthetic assembled datasheet")],
            C1 + "sourceRevision": [text("document-v2")],
        },
    )
    quote = "M-B3 synthetic capacity is 3.9 MWh at 25 C under nominal discharge."
    node(
        "public-part",
        "document-part",
        C1 + "DocumentPart",
        {
            C1 + "partOfDocument": [document],
            C1 + "orderKey": [text("A")],
            C1 + "text": [text(quote)],
            C1 + "partKind": [text("text")],
        },
    )
    node(
        "hidden-part",
        "document-part",
        C1 + "DocumentPart",
        {
            C1 + "partOfDocument": [document],
            C1 + "orderKey": [text("B")],
            DCT + "title": [text("Hidden prototype appendix")],
            C1 + "text": [text("Hidden prototype recipe: violet-electrolyte-token.")],
            C1 + "partKind": [text("text")],
        },
        "bat-hidden",
    )
    assertion("datasheet-source", document, DCT + "source", ids["m-source-a"])
    selector = node(
        "quote-selector",
        "selector",
        C1 + "Selector",
        {
            C1 + "selectorKind": [text("TextQuoteSelector")],
            OA + "exact": [text(quote)],
        },
    )

    def quantity(
        key: str,
        version: str,
        predicate: str,
        value: str,
        source: str,
        unit: str | None,
        conditions: str,
        *,
        duplicate: bool = False,
        scope: str = "bat-robotelier",
        with_part: bool = False,
        part_key: str = "public-part",
    ) -> None:
        claim = identifier(key, "assertion")
        evidence_ids = [
            identifier(key + f"-evidence-{n}", "evidence") for n in range(1, 3 if duplicate else 2)
        ]
        assertion(
            key,
            ids[version],
            B + predicate,
            text(value, "decimal"),
            evidence=evidence_ids,
            interval=interval if version == "m-b3" else None,
            scope=scope,
        )
        measurement = entity(
            key + "-measurement", key + " measurement", B + "Measurement", scope=scope
        )
        assertion(key + "-measurement-ref", claim, B + "measurementRef", measurement, scope=scope)
        if unit:
            assertion(key + "-unit", measurement, B + "unit", text(unit), scope=scope)
        assertion(key + "-conditions", measurement, B + "conditions", text(conditions), scope=scope)
        assertion(
            key + "-measured-on",
            measurement,
            B + "measuredOn",
            text("2026-03-01", "date"),
            scope=scope,
        )
        for n, evidence_id in enumerate(evidence_ids, 1):
            activity_id = identifier(key + f"-import-{n}", "activity")
            props: dict[str, Any] = {
                C1 + "assertionRef": [claim],
                OA + "hasSource": [ids[source]],
                C1 + "sourceRevision": [text("source-v1")],
                PROV + "wasGeneratedBy": [activity_id],
                C1 + "excerpt": [
                    text(
                        (
                            quote
                            if part_key == "public-part"
                            else "Hidden prototype recipe: violet-electrolyte-token."
                        )
                        if with_part
                        else f"{version.upper()} synthetic {predicate}: {value} "
                        + f"{unit or '(unit absent)'}. "
                        + conditions
                    )
                ],
            }
            if with_part:
                props[OA + "hasSource"] = [ids[part_key]]
                props[C1 + "sourceRevision"] = [text("document-v2")]
                if part_key == "public-part":
                    props[OA + "hasSelector"] = [selector]
            node(key + f"-evidence-{n}", "evidence", C1 + "Evidence", props, scope)
            node(
                key + f"-import-{n}",
                "activity",
                PROV + "Activity",
                {
                    PROV + "wasAttributedTo": ["urn:c1:fixture:producer:robotelier"],
                    PROV + "used": [ids[source]],
                    C1 + "output": [claim, evidence_id],
                    C1 + "toolName": [text("synthetic-importer")],
                    C1 + "toolVersion": [text("1.0.0")],
                    C1 + "method": [text("fixture-external-import")],
                    C1 + "outcome": [text("imported")],
                },
                scope,
            )

    quantity(
        "o-capacity",
        "o-b1",
        "capacity",
        "2.1",
        "o-source",
        "kWh",
        "25 C; nominal discharge",
        duplicate=True,
    )
    quantity("v-capacity", "v-b2", "capacity", "75", "v-source", "kWh", "20 C; nominal discharge")
    quantity(
        "v-energy-density", "v-b2", "energyDensity", "250", "v-source", None, "20 C; cell level"
    )
    quantity(
        "m-capacity-a",
        "m-b3",
        "capacity",
        "3.9",
        "m-source-a",
        "MWh",
        "25 C; nominal discharge",
        with_part=True,
    )
    quantity(
        "m-capacity-b",
        "m-b3",
        "capacity",
        "3.6",
        "m-source-b",
        "MWh",
        "25 C; nominal discharge",
    )
    quantity(
        "p-capacity",
        "p-b4",
        "capacity",
        "4.2",
        "m-source-a",
        "MWh",
        "Hidden prototype conditions",
        scope="bat-hidden",
        with_part=True,
        part_key="hidden-part",
    )
    # Mutations are separate ChangeSets so the security tests can compare before/after.
    before = len(records["robotelier"])
    assertion(
        "solar-hidden-topic",
        ids["solar"],
        DCT + "subject",
        ids["topic-batteries"],
        scope="bat-hidden",
    )
    hidden_topic = records["robotelier"].pop()
    assert len(records["robotelier"]) == before
    ambiguity: list[dict[str, Any]] = []
    for key, label, scope in (
        ("ambiguous-person", "Tesla Example Person", "bat-shared"),
        ("hidden-tesla", "Hidden Tesla", "bat-hidden"),
    ):
        entity(key, label, scope=scope)
        item = records["robotelier"].pop()
        item["properties"][SKOS + "altLabel"] = [text("Tesla")]
        ambiguity.append(item)
    return {
        "name": "cross-project-batteries",
        "version": "1.0.0",
        "profile": "batteries",
        "scopes": {
            key: key for key in ("bat-shared", "bat-papertrader", "bat-robotelier", "bat-hidden")
        },
        "principals": {
            "dave": ["bat-shared", "bat-papertrader", "bat-robotelier"],
            "carol": ["bat-shared", "bat-papertrader", "bat-robotelier", "bat-hidden"],
        },
        "ids": ids,
        "producers": records,
        "hidden_topic": hidden_topic,
        "ambiguity": ambiguity,
        "quote": quote,
    }


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = directory.parents[1]
    core = json.loads((root / "profiles/core/profile.json").read_text())
    profile = build_profile(core)
    core_shapes = (root / "profiles/core/shapes.ttl").read_text()
    entity_shape = core_shapes.split("<urn:c1:ns:core#shape-Entity>", 1)[1].split("\n\n", 1)[0]
    shapes = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n\n"
        + "\n\n".join(
            f"<{B}shape-{name}>" + entity_shape.replace(f"<{C1}Entity>", f"<{B}{name}>")
            for name in ("Product", "Battery", "BatteryVersion", "Measurement")
        )
        + "\n"
    )
    (directory / "fixture.json").write_text(json.dumps(build_fixture(), indent=2) + "\n")
    for target in (directory / "profile", root / "profiles/available/batteries"):
        (target / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
        (target / "context.jsonld").write_text(
            json.dumps(
                {
                    "@id": "urn:c1:context:batteries:1.0.0",
                    "@context": {"batteries": B},
                },
                indent=2,
            )
            + "\n"
        )
        (target / "shapes.ttl").write_text(shapes)


if __name__ == "__main__":
    main()
