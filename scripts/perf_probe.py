"""M14a performance probe on the reference deployment (development measurements).

    C1_REFERENCE=1 uv run --locked python scripts/perf_probe.py prepare   # fresh S deployment
    C1_REFERENCE=1 uv run --locked python scripts/perf_probe.py measure --out probe.json [--writes]

`measure` issues one request at a time and pairs it with the C1 metrics line
(latency and backend round trips). Writes are optional because they change the
repository: one single-create ChangeSet, then the twin's 36 replaces.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark import corpus as corpus_module  # noqa: E402
from benchmark.client import Bench  # noqa: E402
from benchmark.corpus import C1  # noqa: E402
from benchmark.runner import GRAPH_PREDICATES, Runner  # noqa: E402
from tests.integration.m13 import reference as ref  # noqa: E402


def _metrics_since(since: str) -> list[dict[str, Any]]:
    logs = subprocess.run(
        ["podman", "logs", "--since", since, ref.container("c1")],
        capture_output=True,
        text=True,
    )
    lines = []
    for line in (logs.stdout + logs.stderr).splitlines():
        if line.startswith("{") and '"roundtrips"' in line:
            lines.append(json.loads(line))
    return lines


async def _bench() -> Bench:
    identities = json.loads((ref.DIR / "state/test-identities.json").read_text())
    bench = Bench(ref.ReferenceCase(identities))
    listing = await bench.json("GET", "/v1/access-scopes", actor="erin")
    bench.scopes = {s["label"]: s["id"] for s in listing["access_scopes"]}
    return bench


async def prepare() -> None:
    ref.fresh_deployment()
    ref.provision_identities()
    identities = json.loads((ref.DIR / "state/test-identities.json").read_text())
    bench = Bench(ref.ReferenceCase(identities))
    await bench.setup(corpus_module.SCOPES, corpus_module.VISIBLE)
    loaded = corpus_module.generate(1, attributed=await bench.principal("erin"))
    print(json.dumps(await Runner(bench, loaded).load()))
    await bench.case.close()


async def measure(out: Path, writes: bool) -> None:
    bench = await _bench()
    plain = corpus_module.generate(1)
    company = next(iter(plain.tree))
    alias = sorted(plain.alias_index)[0]
    probes: list[tuple[str, str, str, str, dict[str, Any]]] = [
        ("entity-list-50", "GET", "/v1/entities", "alice", {"params": {"limit": "50"}}),
        ("alias-exact", "GET", "/v1/entities", "alice", {"params": {"alias": alias}}),
        ("keyword-any", "GET", "/v1/entities", "alice", {"params": {"keywords_any": "battery"}}),
        (
            "valid-at",
            "GET",
            "/v1/assertions",
            "alice",
            {
                "params": {
                    "predicate": C1 + "worksFor",
                    "object": company,
                    "valid_at": "2024-01-01T00:00:00Z",
                }
            },
        ),
        (
            "documents-text",
            "GET",
            "/v1/documents",
            "alice",
            {"params": {"text_contains": "tok002"}},
        ),
        (
            "neighborhood",
            "GET",
            f"/v1/entities/{quote(company, safe='')}/neighborhood",
            "alice",
            {"params": {"direction": "out", "predicates": GRAPH_PREDICATES, "depth": "3"}},
        ),
        (
            "context-64k",
            "POST",
            "/v1/context",
            "alice",
            {
                "json": {
                    "profile": "graph-context",
                    "profile_version": "1",
                    "anchor": {"id": company},
                    "budget": {"unit": "bytes", "maximum": 65536},
                }
            },
        ),
        (
            "context-8k-refused",
            "POST",
            "/v1/context",
            "alice",
            {
                "json": {
                    "profile": "graph-context",
                    "profile_version": "1",
                    "anchor": {"id": company},
                    "budget": {"unit": "bytes", "maximum": 8192},
                }
            },
        ),
        ("history", "GET", "/v1/history", "carol", {"params": {"resource_id": company}}),
        ("instance", "GET", "/v1/instance", "carol", {}),
    ]
    results: dict[str, Any] = {}
    for name, method, path, actor, kwargs in probes:
        for attempt in ("cold", "warm"):
            await bench.case.token(actor)  # token issuance outside the measured window
            since = datetime.now(UTC).isoformat()
            started = time.perf_counter()
            response = await bench.request(method, path, actor=actor, **kwargs)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            await asyncio.sleep(1.5)
            metrics = [m for m in _metrics_since(since) if m["path"] == path]
            results[f"{name}/{attempt}"] = {
                "status": response.status_code,
                "client_ms": elapsed,
                "server": metrics[-1] if metrics else None,
            }
            print(
                name,
                attempt,
                response.status_code,
                elapsed,
                metrics[-1]["roundtrips"] if metrics else None,
                flush=True,
            )
    if writes:
        erin = await bench.principal("erin")
        record = corpus_module.twin(plain, erin)[0]
        results["write-create-1"] = await bench.apply(
            [{"kind": "create", "record": record, "scope_id": bench.scopes["bench-hidden"]}]
        )
        loaded = corpus_module.generate(1, attributed=erin)
        twin = [r for r in corpus_module.twin(loaded, erin) if r["id"] != record["id"]]
        results["write-create-twin"] = await bench.apply(
            [
                {"kind": "create", "record": r, "scope_id": bench.scopes["bench-hidden"]}
                for r in twin
            ]
        )
        revised = corpus_module.twin(loaded, erin, generation=2)
        before = {r["id"]: r for r in [record, *twin]}
        changed = [r for r in revised if before.get(r["id"]) != r]
        results["write-replace-36"] = await bench.apply(
            [
                {"kind": "replace", "resource_id": r["id"], "record": r, "reason": "M14a probe"}
                for r in changed
            ]
        )
        print("writes", json.dumps({k: v for k, v in results.items() if k.startswith("write")}))
    out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    await bench.case.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    measure_parser = sub.add_parser("measure")
    measure_parser.add_argument("--out", type=Path, required=True)
    measure_parser.add_argument("--writes", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        asyncio.run(prepare())
    else:
        asyncio.run(measure(args.out, args.writes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
