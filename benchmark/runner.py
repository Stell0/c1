"""Benchmark families on a loaded reference deployment (M14 D5–D10).

Ranks are C1's deterministic order; nothing is re-ranked. Gold comes from the
corpus generator. Fidelity and security are hard pass/fail families.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from benchmark import corpus as corpus_module
from benchmark import metrics
from benchmark.client import Bench, fga_requests_since, memory_peak, storage_bytes
from benchmark.configurations import CONFIGURATIONS
from benchmark.corpus import B, Corpus

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PREDICATES = ",".join(B + p for p in ("hasProduct", "hasComponent", "hasVersion"))
VOLATILE_KEYS = {
    "revision",
    "knowledge_revision",
    "next_cursor",
    "cursor",
    "generated_at",
    "request_id",
    "followup_token",
}
REPEATS = 5
PAGE_CAP = 20


def _ids(items: list[Any]) -> list[str]:
    """IDs in C1's order; document list items wrap the record as {"document": {...}}."""
    result = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("document"), dict):
            item = item["document"]
        if isinstance(item, dict):
            result.append(str(item.get("id") or item["part_id"]))
        else:
            result.append(str(item))
    return result


def _orientation_paths(page: dict[str, Any]) -> list[list[str]]:
    """Node-ID paths of a context page's orientation section, in C1's order."""
    paths = page.get("structured", {}).get("orientation", [])
    return [[str(node["id"]) for node in path.get("nodes", [])] for path in paths]


def canonical(value: Any) -> Any:
    """Remove only declared volatility: revision tokens, cursors, timestamps, request IDs."""
    volatile: set[str] = set()

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in VOLATILE_KEYS and isinstance(child, str):
                    volatile.add(child)
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    def strip(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: strip(v) for k, v in item.items() if k not in VOLATILE_KEYS}
        if isinstance(item, list):
            return [strip(v) for v in item]
        if isinstance(item, str):
            for token in sorted(volatile, key=len, reverse=True):
                if len(token) >= 8:
                    item = item.replace(token, "<volatile>")
        return item

    collect(value)
    return strip(value)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Runner:
    def __init__(self, bench: Bench, corpus: Corpus) -> None:
        self.bench = bench
        self.corpus = corpus
        self.registry_names = ("directory", "topics", "batteries")

    # --- loading -----------------------------------------------------------------
    def operations(
        self, records: list[dict[str, Any]], scope: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "kind": "create",
                "record": r,
                "scope_id": self.bench.scopes[scope or self.corpus.scope_of[r["id"]]],
            }
            for r in records
        ]

    async def load(self) -> dict[str, Any]:
        before = storage_bytes()
        started = time.perf_counter()
        batches = []
        for chunk in self.corpus.chunks(200):
            batches.append(await self.bench.apply(self.operations(chunk)))
        return {
            "changesets": len(batches),
            "records": sum(b["operations"] for b in batches),
            "seconds": round(time.perf_counter() - started, 1),
            "changeset_seconds_median": statistics.median(b["seconds"] for b in batches),
            "storage_bytes_before": before,
            "storage_bytes_after": storage_bytes(),
        }

    # --- T01 storage fidelity -------------------------------------------------------
    async def fidelity(self) -> dict[str, Any]:
        def value(item: Any) -> str:
            # An untagged literal may be served with an explicit null language.
            if isinstance(item, dict) and item.get("language") is None:
                item = {k: v for k, v in item.items() if k != "language"}
            return json.dumps(item, sort_keys=True)

        def norm(record: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": record["id"],
                "types": sorted(record["types"]),
                "properties": {
                    k: sorted(value(v) for v in values)
                    for k, values in record["properties"].items()
                },
            }

        losses: list[dict[str, Any]] = []
        extras: dict[str, int] = {}
        semaphore = asyncio.Semaphore(4)

        async def check(record: dict[str, Any]) -> None:
            async with semaphore:
                response = await self.bench.request(
                    "GET", "/v1/resources/" + quote(record["id"], safe=""), actor="carol"
                )
            if response.status_code != 200:
                losses.append({"id": record["id"], "status": response.status_code})
                return
            expected, actual = norm(record), norm(response.json())
            if expected["types"] != actual["types"]:
                losses.append({"id": record["id"], "field": "types"})
            for key, values in expected["properties"].items():
                if actual["properties"].get(key) != values:
                    losses.append(
                        {
                            "id": record["id"],
                            "field": key,
                            "expected": values,
                            "actual": actual["properties"].get(key),
                        }
                    )
            for key in actual["properties"].keys() - expected["properties"].keys():
                extras[key] = extras.get(key, 0) + 1

        await asyncio.gather(*(check(r) for r in self.corpus.records))
        lost_ids = {loss["id"] for loss in losses}
        total = len(self.corpus.records)

        # Conflicts keep both claims with their evidence.
        conflicts = []
        for version, claims in sorted(self.corpus.measurements.items()):
            if len(claims) < 2:
                continue
            found = await self.bench.json(
                "GET",
                "/v1/assertions",
                actor="carol",
                params={"competing_for": f"{version},{B}capacity", "limit": "50"},
            )
            conflicts.append(sorted(_ids(found.get("items", []))) == sorted(claims))
        # Documents: parts in (order_key, id) order with identical text digests.
        documents = []
        for document, parts in sorted(self.corpus.documents.items()):
            found = await self.bench.json(
                "GET",
                f"/v1/documents/{quote(document, safe='')}/parts",
                actor="carol",
                params={"limit": "200"},
            )
            items = found.get("items", found.get("parts", []))
            texts = [self._text(item) for item in items]
            documents.append(
                _ids(items) == [p["id"] for p in parts]
                and [hashlib.sha256(t.encode()).hexdigest() for t in texts]
                == [hashlib.sha256(p["text"].encode()).hexdigest() for p in parts]
            )
        roundtrip = await self.export_roundtrip()
        exact = total - len(lost_ids)
        return {
            "records": total,
            "exact_records": exact,
            "score": round(exact / total, 6),
            "losses": losses[:50],
            "server_added_properties": dict(sorted(extras.items())),
            "conflicts_checked": len(conflicts),
            "conflicts_preserved": sum(conflicts),
            "documents_checked": len(documents),
            "documents_exact": sum(documents),
            "export_roundtrip": roundtrip,
            "passed": exact == total and all(conflicts) and all(documents) and roundtrip["passed"],
        }

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        value = item.get("text")
        if isinstance(value, str):
            return value
        properties = item.get("properties", {})
        values = properties.get(corpus_module.C1 + "text", [])
        return str(values[0]["lexical"]) if values else ""

    async def export_roundtrip(self) -> dict[str, Any]:
        from c1.interchange.jsonld import import_jsonld
        from c1.model.profiles import ProfileRegistry

        registry = ProfileRegistry()
        for name in self.registry_names:
            registry.load(ROOT / "profiles/available" / name)
        exported: set[str] = set()
        imported: set[str] = set()
        cursor = None
        pages = 0
        while pages < 200:
            params = {"limit": "200", **({"cursor": cursor} if cursor else {})}
            page = await self.bench.json("GET", "/v1/export", actor="carol", params=params)
            snapshot = page["snapshot"]
            ids = {node["@id"] for node in snapshot.get("@graph", [])}
            exported |= ids
            imported |= {record.id for record in import_jsonld(snapshot, registry).records}
            pages += 1
            cursor = page.get("next_cursor")
            if not cursor:
                break
        # /v1/export covers entities, assertions, sources and evidence (the M05
        # snapshot scope); document parts are checked through the parts API.
        exportable = {
            "Entity",
            "Product",
            "Battery",
            "BatteryVersion",
            "Measurement",
            "Assertion",
            "Source",
            "Evidence",
        }
        expected = {
            r["id"] for r in self.corpus.records if r["types"][0].rsplit("#", 1)[-1] in exportable
        }
        return {
            "expected": len(expected),
            "pages": pages,
            "exported": len(exported),
            "corpus_records_exported": len(expected & exported),
            "identities_identical": imported == exported,
            "passed": imported == exported and expected <= exported,
        }

    # --- query execution ----------------------------------------------------------
    async def _pages(
        self, path: str, params: dict[str, str], actor: str, revision: str | None
    ) -> tuple[int, list[dict[str, Any]]]:
        pages: list[dict[str, Any]] = []
        cursor = None
        while len(pages) < PAGE_CAP:
            query = {
                "limit": "200",
                **params,
                **({"revision": revision} if revision else {}),
                **({"cursor": cursor} if cursor else {}),
            }
            response = await self.bench.request("GET", path, actor=actor, params=query)
            if response.status_code != 200:
                return response.status_code, [{"error": response.json()}]
            pages.append(response.json())
            cursor = pages[-1].get("next_cursor")
            if not cursor:
                break
        return 200, pages

    async def _context(
        self, anchor: str, budget: int, actor: str, revision: str | None
    ) -> tuple[int, list[dict[str, Any]]]:
        body: dict[str, Any] = {
            "profile": "graph-context",
            "profile_version": "1",
            "anchor": {"id": anchor},
            "budget": {"unit": "bytes", "maximum": budget},
        }
        if revision:
            body["revision"] = revision
        pages: list[dict[str, Any]] = []
        while len(pages) < PAGE_CAP:
            response = await self.bench.request("POST", "/v1/context", actor=actor, json=body)
            if response.status_code != 200:
                return response.status_code, [{"error": response.json()}]
            pages.append(response.json())
            cursor = pages[-1].get("bounds", {}).get("next_cursor")
            if not cursor:
                break
            body = {**body, "cursor": cursor}
        return 200, pages

    async def execute(
        self,
        query: dict[str, Any],
        strategy: str,
        *,
        actor: str = "alice",
        revision: str | None = None,
    ) -> dict[str, Any]:
        """One observation: status, C1's ranked IDs and the full response pages."""
        family = query["family"]
        started = time.perf_counter()
        if family in {"keyword", "alias", "label-prefix"}:
            status, pages = await self._pages("/v1/entities", query["params"], actor, revision)
            ranked = [i for p in pages for i in _ids(p.get("items", []))]
        elif family == "valid-at":
            status, pages = await self._pages("/v1/assertions", query["params"], actor, revision)
            ranked = [i for p in pages for i in _ids(p.get("items", []))]
        elif family == "document":
            status, pages = await self._pages("/v1/documents", query["params"], actor, revision)
            ranked = [i for p in pages for i in _ids(p.get("items", p.get("documents", [])))]
        elif family == "graph" and strategy == "keyword-only":
            status, pages = await self._pages(
                "/v1/entities", query["keyword_strategy"], actor, revision
            )
            ranked = [i for p in pages for i in _ids(p.get("items", []))]
        elif family == "graph" and strategy == "neighborhood":
            path = f"/v1/entities/{quote(query['anchor'], safe='')}/neighborhood"
            status, pages = await self._pages(
                path,
                {"direction": "out", "predicates": GRAPH_PREDICATES, "depth": "3"},
                actor,
                revision,
            )
            versions = set(self.corpus_versions())
            # The client keeps the need's declared type; C1's order is preserved.
            ranked = [
                i
                for p in pages
                for i in _ids(p.get("nodes", []))
                if i in versions or self._type_of(p, i) == B + "BatteryVersion"
            ]
        elif family in {"graph", "context"}:
            budget = query.get("budget", 65536)
            status, pages = await self._context(query["anchor"], budget, actor, revision)
            ranked = []
            for page in pages:
                for node_path in _orientation_paths(page):
                    node = node_path[-1] if node_path else None
                    if node and node not in ranked and node != query["anchor"]:
                        ranked.append(node)
        else:
            raise ValueError(f"unknown family/strategy {family}/{strategy}")
        return {
            "status": status,
            "ranked": ranked,
            "pages": pages,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def corpus_versions(self) -> list[str]:
        return [
            v
            for company in self.corpus.tree.values()
            for data in company["products"].values()
            for v in data["versions"]
        ]

    @staticmethod
    def _type_of(page: dict[str, Any], identifier: str) -> str | None:
        for node in page.get("nodes", []):
            if isinstance(node, dict) and node.get("id") == identifier:
                types = node.get("types", [])
                return B + "BatteryVersion" if B + "BatteryVersion" in types else None
        return None

    @staticmethod
    def strategies(query: dict[str, Any]) -> tuple[str, ...]:
        if query["family"] == "graph":
            return ("keyword-only", "neighborhood", "graph-context")
        if query["family"] == "context":
            return ("graph-context",)
        return ("exact",)

    async def observe_all(
        self, *, actor: str = "alice", revision: str | None = None
    ) -> dict[str, dict[str, Any]]:
        observed: dict[str, dict[str, Any]] = {}
        for query in self.corpus.queries:
            for strategy in self.strategies(query):
                observed[f"{query['id']}#{strategy}"] = await self.execute(
                    query, strategy, actor=actor, revision=revision
                )
        return observed

    # --- T02 retrieval quality ------------------------------------------------------
    def quality(self, observed: dict[str, dict[str, Any]]) -> dict[str, Any]:
        rows: dict[str, list[dict[str, float]]] = {}
        per_query = {}
        sanity_failures = []
        for query in self.corpus.queries:
            for strategy in self.strategies(query):
                key = f"{query['id']}#{strategy}"
                result = observed[key]
                ranked = result["ranked"]
                row = metrics.summarize(ranked, query["gold"])
                if query["family"] == "graph":
                    row["battery_recall"] = metrics.recall_at(
                        [i for i in self._all_ids(result)], set(query["gold_batteries"]), 10**6
                    )
                    if strategy == "graph-context":
                        found = [p for page in result["pages"] for p in _orientation_paths(page)]
                        row["path_recall"] = metrics.path_recall(found, query["gold_paths"])
                if query["family"] == "context":
                    row.update(self._coverage(query, result))
                if result["status"] != 200:
                    row["error"] = 1.0
                    error = result["pages"][0].get("error", {}) if result["pages"] else {}
                    if isinstance(error.get("minimum_required"), int):
                        row["minimum_required_bytes"] = float(error["minimum_required"])
                per_query[key] = {
                    "status": result["status"],
                    "gold": len(query["gold"]),
                    "returned": len(ranked),
                    **row,
                }
                rows.setdefault(f"{query['family']}/{strategy}", []).append(
                    {k: v for k, v in row.items() if k != "minimum_required_bytes"}
                )
                if query["family"] in {"keyword", "alias", "valid-at", "document"} and (
                    set(ranked) != set(query["gold"])
                ):
                    sanity_failures.append(key)
        return {
            "families": {
                k: {"queries": len(v), **metrics.macro(v)} for k, v in sorted(rows.items())
            },
            "per_query": per_query,
            "exact_semantics_failures": sanity_failures,
        }

    @staticmethod
    def _all_ids(result: dict[str, Any]) -> list[str]:
        text = json.dumps(result["pages"])
        return [token for token in set(text.replace('"', " ").split()) if ":entity/" in token]

    @staticmethod
    def _coverage(query: dict[str, Any], result: dict[str, Any]) -> dict[str, float]:
        required = set(query["required_units"])
        found: set[str] = set()
        pages_needed = 0.0
        first = 0.0
        for n, page in enumerate(result["pages"]):
            for fact in page.get("structured", {}).get("facts", []):
                found |= {c.get("assertion_id") for c in fact.get("claims", [])}
            if n == 0:
                first = metrics.coverage(found, required)
            if required <= found and not pages_needed:
                pages_needed = float(n + 1)
        return {
            "coverage_first_page": first,
            "coverage_all_pages": metrics.coverage(found, required),
            "pages_to_full_coverage": pages_needed,
            "pages": float(len(result["pages"])),
        }

    # --- T03 security invariance ----------------------------------------------------
    @staticmethod
    def fingerprints(observed: dict[str, dict[str, Any]]) -> dict[str, str]:
        return {
            key: digest({"status": value["status"], "pages": canonical(value["pages"])})
            for key, value in observed.items()
        }

    async def security(self, baseline: dict[str, str]) -> dict[str, Any]:
        hidden_scope = "bench-hidden"
        attributed = await self.bench.principal("erin")
        records = corpus_module.twin(self.corpus, attributed)
        added = await self.bench.apply(self.operations(records, hidden_scope))
        after_add = self.fingerprints(await self.observe_all())
        revised = corpus_module.twin(self.corpus, attributed, generation=2)
        changed = [r for r, old in zip(revised, records, strict=True) if r != old]
        modified = await self.bench.apply(
            [
                {
                    "kind": "replace",
                    "resource_id": r["id"],
                    "record": r,
                    "reason": "M14-T03 hidden modification",
                }
                for r in changed
            ]
        )
        after_modify = self.fingerprints(await self.observe_all())
        differing = sorted(
            {k for k in baseline if baseline[k] != after_add.get(k)}
            | {k for k in baseline if baseline[k] != after_modify.get(k)}
        )
        total = 2 * len(baseline)
        identical = (
            total
            - sum(baseline[k] != after_add.get(k) for k in baseline)
            - sum(baseline[k] != after_modify.get(k) for k in baseline)
        )
        return {
            "hidden_records_added": len(records),
            "hidden_records_modified": len(changed),
            "hidden_add_changeset": added,
            "hidden_modify_changeset": modified,
            "observations": total,
            "identical": identical,
            "score": round(identical / total, 6),
            "differing": differing,
            "passed": identical == total,
        }

    # --- T04 revocation -------------------------------------------------------------
    async def revocation(self, baseline: dict[str, str]) -> dict[str, Any]:
        team = {i for i, scope in self.corpus.scope_of.items() if scope == "bench-team"}
        texts = {
            p["text"]
            for parts in self.corpus.documents.values()
            for p in parts
            if p["scope"] == "bench-team"
        }
        old_revision = await self.bench.head()
        await self.bench.revoke("bench-team", "alice", "reader")
        leaks: list[dict[str, Any]] = []
        runs = {}
        for name, revision in (("head", None), ("pre_revocation_revision", old_revision)):
            observed = await self.observe_all(revision=revision)
            runs[name] = len(observed)
            for key, value in observed.items():
                text = json.dumps(value["pages"])
                hit = [i for i in team if i in text] + [t for t in texts if t in text]
                if hit:
                    leaks.append({"run": name, "observation": key, "resources": hit[:5]})
        await self.bench.grant("bench-team", "alice", "reader")
        restored = self.fingerprints(await self.observe_all())
        differing = sorted(k for k in baseline if baseline[k] != restored.get(k))
        return {
            "team_resources": len(team),
            "observations": runs,
            "leaks": leaks[:50],
            "restored_identical": not differing,
            "restored_differing": differing,
            "passed": not leaks and not differing,
        }

    # --- T05 performance ------------------------------------------------------------
    async def performance(self) -> dict[str, Any]:
        samples: dict[str, list[float]] = {}
        fga: dict[str, list[float]] = {}
        context: dict[str, list[float]] = {}
        for query in self.corpus.queries:
            for strategy in self.strategies(query):
                key = f"{query['family']}/{strategy}"
                since = datetime.now(UTC).isoformat()
                for _ in range(REPEATS):
                    result = await self.execute(query, strategy)
                    samples.setdefault(key, []).append(result["latency_ms"])
                    if query["family"] == "context":
                        context.setdefault(str(query["budget"]), []).append(result["latency_ms"])
                fga.setdefault(key, []).append(fga_requests_since(since) / REPEATS)

        def stats(values: list[float]) -> dict[str, float]:
            ordered = sorted(values)
            return {
                "median_ms": statistics.median(ordered),
                "p90_ms": ordered[max(0, int(round(0.9 * len(ordered))) - 1)],
                "max_ms": ordered[-1],
                "samples": float(len(ordered)),
            }

        return {
            "repeats": REPEATS,
            "families": {
                k: {**stats(v), "openfga_requests_per_query": round(statistics.mean(fga[k]), 1)}
                for k, v in sorted(samples.items())
            },
            "context_by_budget": {k: stats(v) for k, v in sorted(context.items())},
            "c1_memory_peak_bytes": memory_peak(),
            "storage_bytes": storage_bytes(),
        }

    # --- T06 configurations ---------------------------------------------------------
    @staticmethod
    def ablations() -> dict[str, Any]:
        return {
            name: (
                {"status": "RUN"}
                if c["available"]
                else {"status": "NOT_AVAILABLE", "reason": c["reason"]}
            )
            for name, c in CONFIGURATIONS.items()
        }
