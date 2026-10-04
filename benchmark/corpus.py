"""Deterministic synthetic corpus `bench-v1` with generator-derived gold (M14 D2, D3).

Everything here is pure: the same seed and scale give byte-identical records,
queries and gold. Gold relevance comes from the generator's own structures and
never from C1 output.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

C1 = "urn:c1:ns:core#"
B = "urn:c1:ns:batteries#"
D = "urn:c1:ns:directory#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PROV = "http://www.w3.org/ns/prov#"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
TIME = "http://www.w3.org/2006/time#"
CORPUS = "bench-v1"
SEED = 14
SCOPES = ("bench-public", "bench-team", "bench-legal", "bench-hidden")
VISIBLE = ("bench-public", "bench-team")  # what the tested principal (alice) reads


def ident(key: str, kind: str) -> str:
    """Name-derived, stable IDs with the UUIDv4 syntax C1 storage requires."""
    named = uuid.uuid5(uuid.NAMESPACE_URL, f"{CORPUS}/{key}")
    return f"urn:c1:instance:dev:{kind}/{uuid.UUID(bytes=named.bytes, version=4)}"


def lit(value: str, datatype: str = "string") -> dict[str, str]:
    return {"lexical": value, "datatype": XSD + datatype}


@dataclass
class Corpus:
    scale: int
    records: list[dict[str, Any]] = field(default_factory=list)
    scope_of: dict[str, str] = field(default_factory=dict)
    queries: list[dict[str, Any]] = field(default_factory=list)
    # Structure used for gold: company -> product -> battery -> versions.
    tree: dict[str, dict[str, Any]] = field(default_factory=dict)
    keyword_index: dict[str, list[str]] = field(default_factory=dict)
    alias_index: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    employments: list[dict[str, Any]] = field(default_factory=list)
    documents: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    measurements: dict[str, list[str]] = field(default_factory=dict)
    # Records sharing a group reference each other and must load in one ChangeSet.
    group_of: dict[str, str] = field(default_factory=dict)
    current_group: str | None = None

    def add(self, record: dict[str, Any], scope: str) -> str:
        self.records.append(record)
        self.scope_of[record["id"]] = scope
        if self.current_group:
            self.group_of[record["id"]] = self.current_group
        return str(record["id"])

    def chunks(self, limit: int = 200) -> list[list[dict[str, Any]]]:
        """Records in generation order, packed into ChangeSets without splitting a group."""
        units: list[list[dict[str, Any]]] = []
        for record in self.records:
            group = self.group_of.get(record["id"])
            if group and units and self.group_of.get(units[-1][-1]["id"]) == group:
                units[-1].append(record)
            else:
                units.append([record])
        batches: list[list[dict[str, Any]]] = [[]]
        for unit in units:
            if len(batches[-1]) + len(unit) > limit:
                batches.append([])
            batches[-1].extend(unit)
        return [b for b in batches if b]

    def visible(self, identifier: str) -> bool:
        return self.scope_of.get(identifier) in VISIBLE

    def manifest(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.records:
            kind = record["types"][0].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            counts[kind] = counts.get(kind, 0) + 1
        return {
            "corpus": CORPUS,
            "seed": SEED,
            "scale": self.scale,
            "records": len(self.records),
            "counts": dict(sorted(counts.items())),
            "visible_to_tested_principal": sum(1 for r in self.records if self.visible(r["id"])),
            "records_sha256": digest(self.records),
            "gold_sha256": digest(self.queries),
        }


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def generate(scale: int = 1, attributed: str = "urn:c1:fixture:producer:bench") -> Corpus:
    rng = random.Random(f"{SEED}-{scale}")
    corpus = Corpus(scale)

    def entity(
        key: str,
        label: str,
        cls: str,
        scope: str,
        *,
        keywords: tuple[str, ...] = (),
        alias: str | None = None,
    ) -> str:
        identifier = ident(key, "entity")
        properties: dict[str, Any] = {
            SKOS + "prefLabel": [lit(label)],
            C1 + "lifecycle": [lit("active")],
        }
        keyword_ids = []
        for word in keywords:
            keyword_id = ident(f"{key}/keyword/{word}", "keyword")
            corpus.add(
                {
                    "id": keyword_id,
                    "types": [C1 + "Keyword"],
                    "properties": {
                        C1 + "keywordText": [lit(word)],
                        C1 + "normalizedKeyword": [lit(word.casefold())],
                        C1 + "normalizationVersion": [lit("c1-kw-1")],
                    },
                },
                scope,
            )
            keyword_ids.append(keyword_id)
            corpus.keyword_index.setdefault(word.casefold(), []).append(identifier)
        if keyword_ids:
            properties[C1 + "keyword"] = keyword_ids
        if alias:
            properties[SKOS + "altLabel"] = [lit(alias)]
            corpus.alias_index[alias] = identifier
        corpus.labels[identifier] = label
        return corpus.add({"id": identifier, "types": [cls], "properties": properties}, scope)

    def assertion(
        key: str,
        subject: str,
        predicate: str,
        value: Any,
        scope: str,
        *,
        evidence: list[str] | None = None,
        interval: str | None = None,
    ) -> str:
        properties: dict[str, Any] = {
            RDF + "subject": [subject],
            RDF + "predicate": [predicate],
            RDF + "object": [value],
            C1 + "origin": [lit("imported" if evidence else "manual")],
            C1 + "reviewState": [lit("reported")],
            C1 + "lifecycle": [lit("active")],
            C1 + "manualStatement": [lit("false" if evidence else "true", "boolean")],
            PROV + "wasAttributedTo": [attributed],
        }
        if evidence:
            properties[C1 + "evidence"] = evidence
        if interval:
            properties[C1 + "validDuring"] = [interval]
        return corpus.add(
            {"id": ident(key, "assertion"), "types": [C1 + "Assertion"], "properties": properties},
            scope,
        )

    def source(key: str, title: str, scope: str) -> str:
        return corpus.add(
            {
                "id": ident(key, "source"),
                "types": [C1 + "Source"],
                "properties": {
                    DCT + "title": [lit(title)],
                    C1 + "sourceKind": [lit("synthetic-datasheet")],
                    C1 + "sourceRevision": [lit("bench-v1")],
                },
            },
            scope,
        )

    def interval(key: str, start: str | None, end: str | None, scope: str) -> str:
        bounds = {}
        for name, value in (("start", start), ("end", end)):
            props: dict[str, Any] = {C1 + "boundaryState": [lit("known" if value else "unknown")]}
            if value and len(value.rstrip("Z")) == 4:
                props[TIME + "inXSDgYear"] = [lit(value, "gYear")]
            elif value:
                props[TIME + "inXSDDateTimeStamp"] = [lit(value, "dateTimeStamp")]
            bounds[name] = corpus.add(
                {
                    "id": ident(f"{key}/{name}", "time-boundary"),
                    "types": [C1 + "TimeBoundary"],
                    "properties": props,
                },
                scope,
            )
        return corpus.add(
            {
                "id": ident(key, "time-interval"),
                "types": [C1 + "TimeInterval"],
                "properties": {
                    TIME + "hasBeginning": [bounds["start"]],
                    TIME + "hasEnd": [bounds["end"]],
                },
            },
            scope,
        )

    def measurement(
        key: str, version: str, value: str, unit: str, scope: str, sources: list[str]
    ) -> str:
        corpus.current_group = key
        try:
            return _measurement(key, version, value, unit, scope, sources)
        finally:
            corpus.current_group = None

    def _measurement(
        key: str, version: str, value: str, unit: str, scope: str, sources: list[str]
    ) -> str:
        evidence_ids = [ident(f"{key}/evidence/{n}", "evidence") for n in range(len(sources))]
        claim = assertion(
            key, version, B + "capacity", lit(value, "decimal"), scope, evidence=evidence_ids
        )
        node = entity(f"{key}/measurement", f"{key} measurement", B + "Measurement", scope)
        assertion(f"{key}/ref", claim, B + "measurementRef", node, scope)
        assertion(f"{key}/unit", node, B + "unit", lit(unit), scope)
        assertion(f"{key}/conditions", node, B + "conditions", lit("25 C; nominal"), scope)
        for n, (evidence_id, source_id) in enumerate(zip(evidence_ids, sources, strict=True)):
            activity = ident(f"{key}/import/{n}", "activity")
            corpus.add(
                {
                    "id": evidence_id,
                    "types": [C1 + "Evidence"],
                    "properties": {
                        C1 + "assertionRef": [claim],
                        OA + "hasSource": [source_id],
                        C1 + "sourceRevision": [lit("bench-v1")],
                        PROV + "wasGeneratedBy": [activity],
                        C1 + "excerpt": [lit(f"{corpus.labels[version]} capacity {value} {unit}")],
                    },
                },
                scope,
            )
            corpus.add(
                {
                    "id": activity,
                    "types": [PROV + "Activity"],
                    "properties": {
                        PROV + "wasAttributedTo": [attributed],
                        PROV + "used": [source_id],
                        C1 + "output": [claim, evidence_id],
                        C1 + "toolName": [lit("bench-generator")],
                        C1 + "toolVersion": [lit("1")],
                        C1 + "method": [lit("synthetic-import")],
                        C1 + "outcome": [lit("imported")],
                    },
                },
                scope,
            )
        corpus.measurements.setdefault(version, []).append(claim)
        return claim

    datasheet = source("datasheets", "Bench synthetic datasheets", "bench-public")
    lab = source("lab", "Bench synthetic laboratory report", "bench-public")
    for c in range(4 * scale):
        company_scope = "bench-public"
        company = entity(
            f"company/{c}",
            f"Bench Company {c:02d}",
            C1 + "Entity",
            company_scope,
            keywords=(f"company-{c:02d}", "bench-company"),
            alias=f"BC{c:02d} Holdings",
        )
        corpus.tree[company] = {"products": {}}
        for p in range(8):
            scope = (
                "bench-team" if p % 4 == 3 else ("bench-legal" if p % 8 == 5 else "bench-public")
            )
            product = entity(
                f"product/{c}/{p}",
                f"Bench Product {c:02d}-{p}",
                B + "Product",
                scope,
                keywords=("bench-product",),
            )
            assertion(f"has-product/{c}/{p}", company, B + "hasProduct", product, scope)
            battery_keywords = ("battery",) if p % 2 == 0 else ()
            battery = entity(
                f"battery/{c}/{p}",
                f"Bench Battery {c:02d}-{p}",
                B + "Battery",
                scope,
                keywords=battery_keywords,
            )
            assertion(f"has-component/{c}/{p}", product, B + "hasComponent", battery, scope)
            versions = []
            for v in range(3):
                version = entity(
                    f"version/{c}/{p}/{v}",
                    f"Bench Version {c:02d}-{p}-{v}",
                    B + "BatteryVersion",
                    scope,
                )
                assertion(f"has-version/{c}/{p}/{v}", battery, B + "hasVersion", version, scope)
                versions.append(version)
            corpus.tree[company]["products"][product] = {"battery": battery, "versions": versions}
            capacity = str(50 + rng.randrange(50))
            sources = [datasheet, lab] if p % 3 == 0 else [datasheet]
            measurement(f"capacity/{c}/{p}", versions[0], capacity, "kWh", scope, sources)
            if p % 3 == 0:
                # A declared conflict: a second, different value from another source.
                measurement(
                    f"capacity-b/{c}/{p}", versions[0], str(int(capacity) + 7), "kWh", scope, [lab]
                )
    people = 24 * scale
    companies = list(corpus.tree)
    for n in range(people):
        person = entity(
            f"person/{n}",
            f"Bench Person {n:03d}",
            C1 + "Entity",
            "bench-public",
            keywords=("bench-person",),
        )
        employers = [companies[n % len(companies)]]
        if n % 3 == 0:
            employers.append(companies[(n + 1) % len(companies)])
        for k, employer in enumerate(employers):
            if n % 8 == 0:
                start, end = "2019", "2022"  # year precision, timezone unknown
            elif n % 8 == 4:
                start, end = "2019Z", "2022Z"  # year precision in UTC
            elif n % 4 == 1:
                start, end = "2021-01-01T00:00:00Z", None
            else:
                start, end = "2023-06-01T00:00:00Z", "2030-01-01T00:00:00Z"
            span = interval(f"employment/{n}/{k}", start, end, "bench-public")
            claim = assertion(
                f"works-for/{n}/{k}",
                person,
                C1 + "worksFor",
                employer,
                "bench-public",
                interval=span,
            )
            corpus.employments.append(
                {
                    "person": person,
                    "company": employer,
                    "start": start,
                    "end": end,
                    "assertion": claim,
                }
            )
    for doc in range(6 * scale):
        document = corpus.add(
            {
                "id": ident(f"document/{doc}", "document"),
                "types": [C1 + "Document"],
                "properties": {
                    DCT + "title": [lit(f"Bench handbook {doc:02d}")],
                    C1 + "sourceRevision": [lit("bench-v1")],
                },
            },
            "bench-public",
        )
        parts = []
        for part in range(6):
            scope = (
                "bench-public",
                "bench-public",
                "bench-team",
                "bench-public",
                "bench-legal",
                "bench-public",
            )[part]
            text = f"Bench handbook {doc:02d} section {part}: maintenance token tok{doc:02d}{part}."
            part_id = corpus.add(
                {
                    "id": ident(f"document/{doc}/part/{part}", "document-part"),
                    "types": [C1 + "DocumentPart"],
                    "properties": {
                        C1 + "partOfDocument": [document],
                        C1 + "orderKey": [lit(f"p{part + 1}")],
                        C1 + "partKind": [lit("text")],
                        C1 + "text": [lit(text)],
                    },
                },
                scope,
            )
            parts.append({"id": part_id, "scope": scope, "text": text})
        corpus.documents[document] = parts
    corpus.queries = build_queries(corpus)
    return corpus


def build_queries(corpus: Corpus) -> list[dict[str, Any]]:
    """Information needs with gold sets restricted to what the tested principal may read."""
    queries: list[dict[str, Any]] = []
    vis = corpus.visible
    companies = list(corpus.tree)
    words = ["battery", "bench-product", "bench-company", "bench-person"]
    words += [f"company-{c:02d}" for c in range(min(len(companies), 6))]
    for word in words:
        queries.append(
            {
                "id": f"kw-any/{word}",
                "family": "keyword",
                "params": {"keywords_any": word},
                "gold": sorted(i for i in corpus.keyword_index.get(word, []) if vis(i)),
            }
        )
    for c in range(min(len(companies), 3)):
        word = f"company-{c:02d}"
        queries.append(
            {
                "id": f"kw-all/bench-company+{word}",
                "family": "keyword",
                "params": {"keywords_all": f"bench-company,{word}"},
                "gold": sorted(i for i in corpus.keyword_index[word] if vis(i)),
            }
        )
    queries.append(
        {
            "id": "kw-all/battery+bench-product",
            "family": "keyword",
            "params": {"keywords_all": "battery,bench-product"},
            "gold": sorted(
                set(corpus.keyword_index["battery"]) & set(corpus.keyword_index["bench-product"])
            ),
        }
    )
    for alias, target in sorted(corpus.alias_index.items())[:6]:
        queries.append(
            {
                "id": f"alias/{alias}",
                "family": "alias",
                "params": {"alias": alias},
                "gold": [target] if vis(target) else [],
            }
        )
    for prefix in (
        "Bench Battery 01-",
        "Bench Battery 03-",
        "Bench Product 02-",
        "Bench Product 00-",
        "Bench Version 01-1-",
        "Bench Person 00",
        "Bench Person 01",
        "Bench Company",
    ):
        gold = sorted(
            i for i, label in corpus.labels.items() if label.startswith(prefix) and vis(i)
        )
        queries.append(
            {
                "id": f"prefix/{prefix}",
                "family": "label-prefix",
                "params": {"label": prefix, "label_mode": "prefix"},
                "gold": gold,
            }
        )

    # Graph needs: batteries and versions of a company through the typed path.
    # Employment valid at an instant: half-open intervals. An unknown boundary, or a
    # bound without a timezone, is indeterminate (ADR-0007: timezone-unknown values
    # keep their uncertainty) and only matches with include_unknown.
    def status(start: str | None, end: str | None, instant: str) -> str:
        if start is None or end is None or not start.endswith("Z") or not end.endswith("Z"):
            return "indeterminate"
        year = len(start.rstrip("Z")) == 4
        lower = f"{start[:4]}-01-01T00:00:00Z" if year else start
        upper = f"{int(end[:4]) + 1}-01-01T00:00:00Z" if len(end.rstrip("Z")) == 4 else end
        return "match" if lower <= instant < upper else "no_match"

    for company in companies[:4]:
        for instant in ("2020-06-01T00:00:00Z", "2024-01-01T00:00:00Z"):
            for unknown in (False, True):
                accepted = {"match", "indeterminate"} if unknown else {"match"}
                gold = sorted(
                    e["assertion"]
                    for e in corpus.employments
                    if e["company"] == company
                    and vis(e["assertion"])
                    and status(e["start"], e["end"], instant) in accepted
                )
                params = {"predicate": C1 + "worksFor", "object": company, "valid_at": instant}
                if unknown:
                    params["include_unknown"] = "true"
                queries.append(
                    {
                        "id": f"valid-at/{corpus.labels[company]}/{instant[:4]}"
                        f"{'/unknown' if unknown else ''}",
                        "family": "valid-at",
                        "params": params,
                        "gold": gold,
                    }
                )
    for company, node in list(corpus.tree.items())[:4]:
        gold_versions, gold_batteries, paths = [], [], []
        for product, data in node["products"].items():
            if not (vis(product) and vis(data["battery"])):
                continue
            gold_batteries.append(data["battery"])
            for version in data["versions"]:
                if vis(version):
                    gold_versions.append(version)
                    paths.append([company, product, data["battery"], version])
        queries.append(
            {
                "id": f"graph/{corpus.labels[company]}",
                "family": "graph",
                "anchor": company,
                "keyword_strategy": {"keywords_any": "battery"},
                "gold": sorted(gold_versions),
                "gold_batteries": sorted(gold_batteries),
                "gold_paths": paths,
            }
        )
    for doc, parts in list(corpus.documents.items())[:3]:
        token = parts[2]["text"].split("token ")[1].rstrip(".")
        queries.append(
            {
                "id": f"doc/{token}",
                "family": "document",
                "params": {"text_contains": token},
                "gold": [doc] if all(vis(p["id"]) for p in parts[2:3]) else [],
            }
        )
    for company in list(corpus.tree)[:2]:
        required = []
        for product, data in corpus.tree[company]["products"].items():
            if vis(product) and vis(data["battery"]) and vis(data["versions"][0]):
                required.extend(corpus.measurements.get(data["versions"][0], []))
        for budget in (8192, 32768, 65536):
            queries.append(
                {
                    "id": f"context/{corpus.labels[company]}/{budget}",
                    "family": "context",
                    "anchor": company,
                    "budget": budget,
                    "required_units": sorted(required),
                    "gold": sorted(required),
                }
            )
    return queries


def twin(
    corpus: Corpus, attributed: str = "urn:c1:fixture:producer:bench", generation: int = 1
) -> list[dict[str, Any]]:
    """Hidden resources designed to be maximally relevant to every query (M14 D7).

    All live in `bench-hidden`, which the tested principal cannot read. Generation 2
    returns the same identities with changed labels, values and text, for replace
    operations. Visible records are never touched.
    """
    mark = "" if generation == 1 else " revised"
    records: list[dict[str, Any]] = []

    def keyword(key: str, word: str) -> str:
        identifier = ident(f"twin/{key}/keyword/{word}", "keyword")
        records.append(
            {
                "id": identifier,
                "types": [C1 + "Keyword"],
                "properties": {
                    C1 + "keywordText": [lit(word)],
                    C1 + "normalizedKeyword": [lit(word.casefold())],
                    C1 + "normalizationVersion": [lit("c1-kw-1")],
                },
            }
        )
        return identifier

    def entity(
        key: str, label: str, cls: str, words: tuple[str, ...] = (), alias: str | None = None
    ) -> str:
        identifier = ident(f"twin/{key}", "entity")
        properties: dict[str, Any] = {
            SKOS + "prefLabel": [lit(label + mark)],
            C1 + "lifecycle": [lit("active")],
        }
        if words:
            properties[C1 + "keyword"] = [keyword(key, w) for w in words]
        if alias:
            properties[SKOS + "altLabel"] = [lit(alias)]
        records.append({"id": identifier, "types": [cls], "properties": properties})
        return identifier

    def assertion(
        key: str, subject: str, predicate: str, value: Any, extra: dict[str, Any] | None = None
    ) -> str:
        identifier = ident(f"twin/{key}", "assertion")
        properties: dict[str, Any] = {
            RDF + "subject": [subject],
            RDF + "predicate": [predicate],
            RDF + "object": [value],
            C1 + "origin": [lit("manual")],
            C1 + "reviewState": [lit("reported")],
            C1 + "lifecycle": [lit("active")],
            C1 + "manualStatement": [lit("true", "boolean")],
            PROV + "wasAttributedTo": [attributed],
            **(extra or {}),
        }
        records.append({"id": identifier, "types": [C1 + "Assertion"], "properties": properties})
        return identifier

    words = (
        "battery",
        "bench-product",
        "bench-company",
        "bench-person",
        *(f"company-{c:02d}" for c in range(min(len(corpus.tree), 6))),
    )
    entity("all-keywords", "Bench Battery 01-9", B + "Battery", words)
    for n, (alias, _target) in enumerate(sorted(corpus.alias_index.items())[:6]):
        entity(f"alias/{n}", f"Bench Company 9{n}", C1 + "Entity", ("bench-company",), alias)
    for n, prefix in enumerate(
        (
            "Bench Battery 03-",
            "Bench Product 02-",
            "Bench Product 00-",
            "Bench Version 01-1-",
            "Bench Person 00",
            "Bench Person 01",
        )
    ):
        cls = B + "Product" if "Product" in prefix else C1 + "Entity"
        entity(f"prefix/{n}", f"{prefix}9", cls, ("bench-product",))
    companies = list(corpus.tree)
    for c, company in enumerate(companies[:4]):
        product = entity(
            f"product/{c}", f"Bench Product {c:02d}-9", B + "Product", ("bench-product",)
        )
        battery = entity(f"battery/{c}", f"Bench Battery {c:02d}-9", B + "Battery", ("battery",))
        version = entity(f"version/{c}", f"Bench Version {c:02d}-9-0", B + "BatteryVersion")
        assertion(f"has-product/{c}", company, B + "hasProduct", product)
        assertion(f"has-component/{c}", product, B + "hasComponent", battery)
        assertion(f"has-version/{c}", battery, B + "hasVersion", version)
        # Hidden edges between visible nodes must not create matches or paths.
        other = companies[(c + 1) % len(companies)]
        visible_product = next(p for p in corpus.tree[other]["products"] if corpus.visible(p))
        assertion(f"cross-product/{c}", company, B + "hasProduct", visible_product)
        first = next(p for p in corpus.tree[company]["products"] if corpus.visible(p))
        data = corpus.tree[company]["products"][first]
        assertion(
            f"cross-version/{c}",
            data["battery"],
            B + "hasVersion",
            corpus.tree[other]["products"][visible_product]["versions"][1],
        )
        # A competing hidden measurement on a visible version.
        value = str(900 + c + generation)
        assertion(f"capacity/{c}", data["versions"][0], B + "capacity", lit(value, "decimal"))
        # Hidden employment of visible people, valid at both benchmark instants.
        start = ident(f"twin/employment/{c}/start", "time-boundary")
        end = ident(f"twin/employment/{c}/end", "time-boundary")
        span = ident(f"twin/employment/{c}", "time-interval")
        records.append(
            {
                "id": start,
                "types": [C1 + "TimeBoundary"],
                "properties": {
                    C1 + "boundaryState": [lit("known")],
                    TIME + "inXSDDateTimeStamp": [lit("2010-01-01T00:00:00Z", "dateTimeStamp")],
                },
            }
        )
        records.append(
            {
                "id": end,
                "types": [C1 + "TimeBoundary"],
                "properties": {
                    C1 + "boundaryState": [lit("known")],
                    TIME + "inXSDDateTimeStamp": [lit("2040-01-01T00:00:00Z", "dateTimeStamp")],
                },
            }
        )
        records.append(
            {
                "id": span,
                "types": [C1 + "TimeInterval"],
                "properties": {TIME + "hasBeginning": [start], TIME + "hasEnd": [end]},
            }
        )
        person = corpus.employments[c]["person"]
        assertion(f"works-for/{c}", person, C1 + "worksFor", company, {C1 + "validDuring": [span]})
    for d, (document, parts) in enumerate(list(corpus.documents.items())[:3]):
        token = parts[2]["text"].split("token ")[1].rstrip(".")
        records.append(
            {
                "id": ident(f"twin/document/{d}/part", "document-part"),
                "types": [C1 + "DocumentPart"],
                "properties": {
                    C1 + "partOfDocument": [document],
                    C1 + "orderKey": [lit("p3a")],
                    C1 + "partKind": [lit("text")],
                    C1 + "text": [lit(f"Hidden note{mark}: token {token} {token}.")],
                },
            }
        )
        hidden_doc = ident(f"twin/document/{d}", "document")
        records.append(
            {
                "id": hidden_doc,
                "types": [C1 + "Document"],
                "properties": {
                    DCT + "title": [lit(f"Bench handbook {d:02d}{mark}")],
                    C1 + "sourceRevision": [lit("bench-v1")],
                },
            }
        )
        records.append(
            {
                "id": ident(f"twin/document/{d}/own-part", "document-part"),
                "types": [C1 + "DocumentPart"],
                "properties": {
                    C1 + "partOfDocument": [hidden_doc],
                    C1 + "orderKey": [lit("p1")],
                    C1 + "partKind": [lit("text")],
                    C1 + "text": [lit(f"Hidden handbook{mark}: token {token}.")],
                },
            }
        )
    return records
