"""M13-T07 measured bounds on the reference deployment (D11).

Run after the reference acceptance phase, on the same loaded deployment:

    C1_REFERENCE=1 uv run --locked python scripts/bench_m13.py --out docs/evidence/M13/bench.json

Synthetic datasets go into one scope that only the benchmark reader (frank)
can read, so other fixtures do not change the measured candidate counts.
Every number is a measurement on the declared host; nothing is extrapolated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.integration.m04.conftest import action, new_changeset  # noqa: E402
from tests.integration.m07.conftest import request_body  # noqa: E402
from tests.integration.m11.conftest import target, update  # noqa: E402
from tests.integration.m13 import reference as ref  # noqa: E402

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"
REPEATS = 5
DATASETS = (("B1", 300), ("B2", 1000), ("B3", 1500))  # entities; 2 assertions each


def _lit(text: str, datatype: str = XSD + "string") -> dict[str, str]:
    return {"lexical": text, "datatype": datatype}


def _entity(index: int) -> dict[str, Any]:
    return {
        "id": f"urn:c1:instance:dev:entity/{uuid.uuid4()}",
        "types": [C1 + "Entity"],
        "properties": {
            SKOS + "prefLabel": [_lit(f"Bench entity {index:05d}")],
            C1 + "lifecycle": [_lit("active")],
        },
    }


def _assertion(subject: str, obj: str, attributed: str) -> dict[str, Any]:
    return {
        "id": f"urn:c1:instance:dev:assertion/{uuid.uuid4()}",
        "types": [C1 + "Assertion"],
        "properties": {
            RDF + "subject": [subject],
            RDF + "predicate": [C1 + "worksFor"],
            RDF + "object": [obj],
            C1 + "origin": [_lit("manual")],
            C1 + "reviewState": [_lit("reported")],
            C1 + "lifecycle": [_lit("active")],
            C1 + "manualStatement": [_lit("true", XSD + "boolean")],
            "http://www.w3.org/ns/prov#wasAttributedTo": [attributed],
        },
    }


def _host() -> dict[str, Any]:
    def run(*argv: str) -> str:
        return subprocess.run(argv, capture_output=True, text=True).stdout.strip()

    cpu = [line for line in run("lscpu").splitlines() if line.startswith(("Model name", "CPU(s)"))]
    return {
        "hostname": platform.node(),
        "kernel": platform.release(),
        "cpu": cpu,
        "memory": run("free", "-m").splitlines()[1] if run("free", "-m") else "",
        "load": run("cat", "/proc/loadavg"),
        "podman": run("podman", "--version"),
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def _memory_peak() -> int | None:
    out = subprocess.run(
        ["podman", "exec", ref.container("c1"), "cat", "/sys/fs/cgroup/memory.peak"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return int(out) if out.isdigit() else None


def _fga_requests_since(since: str) -> int:
    logs = subprocess.run(
        ["podman", "logs", "--since", since, ref.container("openfga")],
        capture_output=True,
        text=True,
    )
    return (logs.stdout + logs.stderr).count("grpc_req_complete")


async def _timed(call: Any, repeats: int = REPEATS) -> dict[str, Any]:
    samples, statuses, sizes = [], [], []
    for _ in range(repeats):
        started = time.perf_counter()
        response = await call()
        samples.append(round((time.perf_counter() - started) * 1000, 1))
        statuses.append(response.status_code)
        sizes.append(len(response.content))
    return {
        "median_ms": statistics.median(samples),
        "max_ms": max(samples),
        "samples_ms": samples,
        "statuses": sorted(set(statuses)),
        "response_bytes": max(sizes),
    }


async def _apply(case: Any, operations: list[dict[str, Any]]) -> dict[str, float]:
    started = time.perf_counter()
    proposal = await new_changeset(case, operations, actor="erin", key=uuid.uuid4().hex)
    created = time.perf_counter()
    state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
    if state == "submitted":
        state = (await action(case, proposal["id"], "validate", actor="erin"))["state"]
    validated = time.perf_counter()
    assert state == "validated", state
    assert (await action(case, proposal["id"], "approve", actor="carol"))["state"] == "approved"
    approved = time.perf_counter()
    assert (await action(case, proposal["id"], "apply", actor="carol"))["state"] == "applied"
    applied = time.perf_counter()
    return {
        "create_ms": round((created - started) * 1000, 1),
        "validate_ms": round((validated - created) * 1000, 1),
        "approve_ms": round((approved - validated) * 1000, 1),
        "apply_ms": round((applied - approved) * 1000, 1),
    }


async def bench(out: Path) -> dict[str, Any]:
    identities = json.loads((ref.DIR / "state/test-identities.json").read_text())
    case: Any = ref.ReferenceCase(identities)
    result: dict[str, Any] = {"host_before": _host(), "datasets": {}, "limits": {}}
    try:
        scope = await case.scope("M13 benchmark data")
        for role in ("reviewer", "reader"):
            await case.grant(scope, "carol", role)
        await case.grant(scope, "frank", "reader")
        # Write-cost measurements use a scope the benchmark reader cannot read.
        writes = await case.scope("M13 benchmark writes")
        for role in ("reviewer", "reader"):
            await case.grant(writes, "carol", role)
        erin = (await case.principal("erin")).id

        # Context, document and fixture-level measurements on the loaded fixtures.
        loaded_dave = {"revision": None}
        body = request_body(loaded_dave)
        body.pop("revision")
        result["context_graph"] = await _timed(
            lambda: case.request("POST", "/v1/context", actor="dave", json=body)
        )
        update_body = update(target("a2", "b2"))
        result["context_documentation_update"] = await _timed(
            lambda: case.request("POST", "/v1/context", actor="bob", json=update_body)
        )
        result["document_render"] = await _timed(
            lambda: case.request(
                "GET",
                f"/v1/documents/{quote(DOCUMENT, safe='')}/render",
                actor="bob",
                params={"format": "markdown"},
            )
        )
        small = {**body, "budget": {"unit": "bytes", "maximum": 2048}}
        over = await case.request("POST", "/v1/context", actor="dave", json=small)
        result["limits"]["context_below_one_unit"] = {
            "status": over.status_code,
            "code": over.json().get("code"),
            "minimum_required": over.json().get("minimum_required"),
        }
        big = await case.client.post(
            "/v1/context",
            content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
            headers={
                "Authorization": "Bearer " + await case.token("dave"),
                "Content-Type": "application/json",
            },
        )
        result["limits"]["body_over_1_mib"] = {"status": big.status_code}

        # ChangeSet cost at 1, 50 and 200 operations.
        result["changeset"] = {}
        for size in (1, 50, 200):
            operations = [
                {"kind": "create", "record": _entity(i), "scope_id": writes} for i in range(size)
            ]
            result["changeset"][str(size)] = await _apply(case, operations)

        # Concurrent writers on one base.
        result["concurrency"] = {}
        for writers in (2, 4):
            head = await case.knowledge.head()
            ids = []
            for _ in range(writers):
                proposal = await new_changeset(
                    case,
                    [{"kind": "create", "record": _entity(0), "scope_id": writes}],
                    actor="erin",
                    base_revision=head,
                    key=uuid.uuid4().hex,
                )
                state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
                if state == "submitted":
                    await action(case, proposal["id"], "validate", actor="erin")
                await action(case, proposal["id"], "approve", actor="carol")
                ids.append(proposal["id"])

            async def apply(changeset: str) -> int:
                response = await case.request(
                    "POST",
                    f"/v1/changesets/{changeset}/apply",
                    actor="carol",
                    headers={"Idempotency-Key": uuid.uuid4().hex},
                )
                return int(response.status_code)

            started = time.perf_counter()
            statuses = await asyncio.gather(*(apply(c) for c in ids))
            states = []
            for changeset in ids:
                current = await case.request("GET", f"/v1/changesets/{changeset}", actor="carol")
                states.append(current.json()["state"])
            result["concurrency"][str(writers)] = {
                "statuses": sorted(statuses),
                "states": sorted(states),
                "applied": states.count("applied"),
                "wall_ms": round((time.perf_counter() - started) * 1000, 1),
            }

        # Datasets: grow to each size, then measure reads as the benchmark reader.
        present = 0
        anchor = None
        for name, entities in DATASETS:
            load_started = time.perf_counter()
            while present < entities:
                batch = min(66, entities - present)
                records = [_entity(present + i) for i in range(batch)]
                operations = [{"kind": "create", "record": r, "scope_id": scope} for r in records]
                for record in records:
                    target_id = anchor or record["id"]
                    for _ in range(2):
                        operations.append(
                            {
                                "kind": "create",
                                "record": _assertion(record["id"], target_id, erin),
                                "scope_id": scope,
                            }
                        )
                anchor = anchor or records[0]["id"]
                await _apply(case, operations)
                present += batch
            load_seconds = round(time.perf_counter() - load_started, 1)
            since = datetime.now(UTC).isoformat()
            listing = await _timed(
                lambda: case.request("GET", "/v1/entities", actor="frank", params={"limit": "50"})
            )
            fga_per_request = _fga_requests_since(since) / REPEATS
            search = await _timed(
                lambda: case.request(
                    "GET",
                    "/v1/entities",
                    actor="frank",
                    params={"label": "Bench entity 00042", "label_mode": "exact"},
                )
            )
            subject = str(anchor)
            assertions = await _timed(
                lambda: case.request(
                    "GET",
                    "/v1/assertions",
                    actor="frank",
                    params={"subject": subject, "limit": "50"},  # noqa: B023
                )
            )
            count = (
                (await case.request("GET", "/v1/entities", actor="frank", params={"limit": "1"}))
                .json()
                .get("count")
            )
            result["datasets"][name] = {
                "entities_in_scope": present,
                "assertions_in_scope": present * 2,
                "readable_entities_reported": count,
                "load_seconds_cumulative_step": load_seconds,
                "entity_list": listing,
                "entity_label_search": search,
                "assertion_query": assertions,
                "openfga_requests_per_list_request": fga_per_request,
                "c1_memory_peak_bytes": _memory_peak(),
            }

        # Backup and restore cost at the largest dataset.
        work = Path(subprocess.run(["mktemp", "-d"], capture_output=True, text=True).stdout.strip())
        backup = ref.admin("backup", "--to", str(work / "bench"), "--knowledge-only")
        restore = ref.admin("restore-knowledge", "--from", str(work / "bench"))
        result["backup_restore"] = {
            "backup_seconds": backup["seconds"],
            "backup_bytes": backup["sizes"],
            "restore_seconds": restore["seconds"],
        }
        subprocess.run(["rm", "-rf", str(work)])

        # Past the candidate limit: an explicit 422, never a partial page.
        while present < 1800:
            records = [_entity(present + i) for i in range(66)]
            operations = [{"kind": "create", "record": r, "scope_id": scope} for r in records]
            for record in records:
                for _ in range(2):
                    operations.append(
                        {
                            "kind": "create",
                            "record": _assertion(record["id"], record["id"], erin),
                            "scope_id": scope,
                        }
                    )
            await _apply(case, operations)
            present += 66
        beyond = await case.request("GET", "/v1/entities", actor="frank", params={"limit": "50"})
        result["limits"]["candidates_over_5000"] = {
            "resources_in_scope": present * 3,
            "status": beyond.status_code,
            "code": beyond.json().get("code"),
        }
        result["host_after"] = _host()
    finally:
        await case.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs/evidence/M13/bench.json"))
    args = parser.parse_args()
    result = asyncio.run(bench(Path(args.out)))
    source = Path(args.out).resolve().relative_to(ROOT).as_posix()
    (ROOT / "docs/operations/limits.md").write_text(render_limits(result, source))
    print("bench: wrote", args.out, "and docs/operations/limits.md")
    return 0


def render_limits(result: dict[str, Any], source: str = "docs/evidence/M13/bench.json") -> str:
    """docs/operations/limits.md: configured limits plus the measured numbers."""
    host = result["host_before"]
    budget_ms = 30_000  # the reference deployment's C1_QUERY_TIME_BUDGET_MS

    def ms(entry: dict[str, Any]) -> str:
        text = f"{entry['median_ms']:.0f} ms (max {entry['max_ms']:.0f})"
        statuses = entry.get("statuses", [200])
        if statuses != [200]:
            # A refused request is a measured limit behavior, not a latency.
            text += " — HTTP " + ", ".join(str(s) for s in statuses)
        return text

    lines = [
        "# Limits and measured behavior",
        "",
        f"Generated by `scripts/bench_m13.py` from [{source}](../../{source}). "
        "All numbers are measurements of release candidate 0.1.0rc1 on the declared host, "
        "through the reference deployment's TLS proxy; they are not capacity claims for "
        "other hardware or data.",
        "",
        "## Declared host",
        "",
        f"- Host: `{host['hostname']}`, kernel {host['kernel']}, {host['podman']}",
        f"- CPU: {'; '.join(host['cpu'])}",
        f"- Memory (`free -m` row): `{host['memory']}`",
        f"- Load average before: `{host['load']}`; after: "
        f"`{result.get('host_after', {}).get('load', 'n/a')}`",
        "- Settings: query budget 30,000 ms, backend timeout 30 s, OpenFGA deadline 30 s",
        "",
        "## Configured limits",
        "",
        "| Limit | Value | Behavior when exceeded |",
        "|---|---|---|",
        "| Request body | 1 MiB | 413 (measured: "
        f"{result['limits']['body_over_1_mib']['status']}) |",
        "| Readable candidates per query | 5,000 | 422 `C1-QY-052`, no partial page (measured: "
        f"{result['limits']['candidates_over_5000']['status']} "
        f"`{result['limits']['candidates_over_5000']['code']}` with "
        f"{result['limits']['candidates_over_5000']['resources_in_scope']} resources) |",
        "| Readable scopes per principal | 500 | 422 `C1-QY-050` |",
        "| Page size | 1–200 (default 50) | 422 `C1-QY-010` |",
        "| Traversal | depth 3, 500 nodes, 2,000 edges | explicit truncation or 422 |",
        "| Context budget | 2,048–524,288 bytes (default 65,536) | whole units only; below one "
        f"unit 422 `C1-CX-010` (measured: {result['limits']['context_below_one_unit']['status']}, "
        f"minimum {result['limits']['context_below_one_unit']['minimum_required']} bytes) |",
        "| ChangeSet size | 200 operations | 400 |",
        "| Query time budget | 10,000 ms default, max 30,000 | 503 `C1-QY-053`, no partial page |",
        "",
        "## Reads as the dataset grows",
        "",
        "One scope readable by the benchmark reader; each entity has two relationship "
        "assertions. Five repeats per measurement.",
        "",
        "| Dataset | Entities | Assertions | Entity list (50) | Label search | Assertion query "
        "| OpenFGA requests per list | C1 memory peak |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, data in result["datasets"].items():
        peak = data["c1_memory_peak_bytes"]
        lines.append(
            f"| {name} | {data['entities_in_scope']} | {data['assertions_in_scope']} | "
            f"{ms(data['entity_list'])} | {ms(data['entity_label_search'])} | "
            f"{ms(data['assertion_query'])} | {data['openfga_requests_per_list_request']:.1f} | "
            f"{(peak or 0) / 1048576:.0f} MiB |"
        )
    lines += [
        "",
        "## Context and documents (loaded fixtures)",
        "",
        "| Request | Latency | Response size |",
        "|---|---|---|",
        f"| `graph-context` (batteries, dave) | {ms(result['context_graph'])} | "
        f"{result['context_graph']['response_bytes']} bytes |",
        "| `documentation-update` (software, bob) | "
        f"{ms(result['context_documentation_update'])} | "
        f"{result['context_documentation_update']['response_bytes']} bytes |",
        f"| Document render (scoped handbook, bob) | {ms(result['document_render'])} | "
        f"{result['document_render']['response_bytes']} bytes |",
        "",
        "## Writes",
        "",
        "| Operations per ChangeSet | Create | Validate | Approve | Apply |",
        "|---|---|---|---|---|",
    ]
    for size, data in result["changeset"].items():
        lines.append(
            f"| {size} | {data['create_ms']:.0f} ms | {data['validate_ms']:.0f} ms | "
            f"{data['approve_ms']:.0f} ms | {data['apply_ms']:.0f} ms |"
        )
    lines += [
        "",
        "Concurrent writers on one base revision (all approved, applied at once): "
        "exactly one applies; the others are refused as stale and must rebase.",
        "",
        "| Writers | Applied | States | HTTP statuses |",
        "|---|---|---|---|",
    ]
    for writers, data in result["concurrency"].items():
        lines.append(
            f"| {writers} | {data['applied']} | {', '.join(data['states'])} | "
            f"{', '.join(str(s) for s in data['statuses'])} |"
        )
    backup = result["backup_restore"]
    lines += [
        "",
        "## Backup and restore (largest dataset plus fixtures)",
        "",
        f"- Quiesced knowledge-only backup: {backup['backup_seconds']} s, "
        f"{sum(backup['backup_bytes'].values()) / 1048576:.1f} MiB",
        f"- Knowledge-only restore: {backup['restore_seconds']} s",
        "",
    ]
    refused = [
        name
        for name, data in result["datasets"].items()
        if any(
            data[key]["statuses"] != [200]
            for key in ("entity_list", "entity_label_search", "assertion_query")
        )
    ]
    beyond = result["limits"]["candidates_over_5000"]
    if refused:
        served = [n for n in result["datasets"] if n not in refused]
        lines += [
            "## Time budget on this host",
            "",
            f"- Reads at {', '.join(refused)} exceeded the {budget_ms:,} ms query time budget and "
            "returned 503 `C1-QY-053` with no partial page"
            + (f"; {', '.join(served)} completed within it." if served else "."),
            f"- With {beyond['resources_in_scope']} readable resources the response was "
            f"{beyond['status']} `{beyond['code']}`."
            + (
                " The candidate limit (422 `C1-QY-052`) is evaluated after the provisional "
                "candidate snapshot, which already exhausted the time budget here, so this run "
                "did not reach it."
                if beyond["code"] != "C1-QY-052"
                else ""
            ),
            "- Per-request cost grows with the number of readable resources: C1 reads candidate "
            "content in per-class chunks and checks each candidate with OpenFGA (column above).",
            "",
        ]
    lines += [
        "## Not measured",
        "",
        "- Throughput under sustained load, multi-process deployments and high availability.",
    ]
    if not refused:
        lines.append(
            "- The query time-budget limit was not triggered by these datasets; its 503 behavior "
            "is covered by M05-T06 with an injected slow backend."
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
