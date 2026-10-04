"""`python -m benchmark run|compare` (M14 D11, D12).

    C1_REFERENCE=1 uv run --locked python -m benchmark run --scale S --out docs/evidence/M14
    uv run --locked python -m benchmark compare --baseline benchmark/baselines/v1-makako.json \
        --results docs/evidence/M14/results-S.json

`run` bootstraps a fresh reference deployment per scale and tears it down
afterwards unless --keep is given. Credentials are never written to results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import corpus as corpus_module  # noqa: E402
from benchmark.compare import compare  # noqa: E402

SCALES = {"S": 1, "M": 3}


def _revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


def _dirty() -> bool:
    return bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


async def _run_scale(name: str, out: Path, log: Any) -> dict[str, Any]:
    from benchmark.client import Bench
    from benchmark.runner import Runner
    from scripts.bench_m13 import _host
    from tests.integration.m13 import reference as ref

    scale = SCALES[name]
    plain = corpus_module.generate(scale)
    manifest = plain.manifest()
    (out / f"corpus-manifest-{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / f"gold-{name}.json").write_text(json.dumps(plain.queries, indent=1) + "\n")
    log(f"[{name}] corpus {manifest['records']} records, {len(plain.queries)} needs")

    # Development only: reuse a loaded deployment kept by --keep. Gates never set it.
    reuse = os.environ.get("C1_BENCH_REUSE") == "1"
    started = time.perf_counter()
    if reuse:
        bootstrap = json.loads((ref.DIR / "state/bootstrap.json").read_text())
        identities = json.loads((ref.DIR / "state/test-identities.json").read_text())
    else:
        bootstrap = ref.fresh_deployment()
        identities = ref.provision_identities()
    log(f"[{name}] deployment ready in {time.perf_counter() - started:.0f}s (reuse={reuse})")
    case = ref.ReferenceCase(identities)
    result: dict[str, Any] = {
        "corpus": manifest,
        "c1_revision": _revision(),
        "working_tree_modified": _dirty(),
        "c1_version": bootstrap.get("version"),
        "host": _host(),
        "configurations": {},
    }
    try:
        bench = Bench(case)
        if reuse:
            listing = await bench.json("GET", "/v1/access-scopes", actor="erin")
            bench.scopes = {s["label"]: s["id"] for s in listing["access_scopes"]}
        else:
            await bench.setup(corpus_module.SCOPES, corpus_module.VISIBLE)
        attributed = await bench.principal("erin")
        loaded = corpus_module.generate(scale, attributed=attributed)
        assert loaded.queries == plain.queries, "gold must not depend on the deployment"
        runner = Runner(bench, loaded)
        result["load"] = {"reused": True} if reuse else await runner.load()
        log(f"[{name}] loaded in {result['load'].get('seconds', 'n/a (reused)')}s")
        result["fidelity"] = await runner.fidelity()
        log(
            f"[{name}] fidelity {result['fidelity']['score']} passed={result['fidelity']['passed']}"
        )
        observed = await runner.observe_all()
        baseline = runner.fingerprints(observed)
        result["quality"] = runner.quality(observed)
        result["observation_digests"] = baseline
        log(
            f"[{name}] quality: {len(result['quality']['per_query'])} observations, "
            f"exact-semantics failures {result['quality']['exact_semantics_failures']}"
        )
        result["performance"] = await runner.performance()
        log(f"[{name}] performance done")
        result["security"] = await runner.security(baseline)
        log(f"[{name}] security {result['security']['score']}")
        result["revocation"] = await runner.revocation(baseline)
        log(f"[{name}] revocation passed={result['revocation']['passed']}")
        result["configurations"] = runner.ablations()
        result["host_after"] = _host()
    finally:
        await case.close()
    return result


def run(args: argparse.Namespace) -> int:
    from tests.integration.m13 import reference as ref

    for variable in ref.AI_VARIABLES:
        if variable in os.environ:
            print(f"benchmark: {variable} must be unset", file=sys.stderr)
            return 2
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "run.log").open("a")

    def log(message: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    status = 0
    for name in args.scale:
        try:
            result = asyncio.run(_run_scale(name, out, log))
        finally:
            if not args.keep:
                ref.teardown()
        path = out / f"results-{name}.json"
        path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        hard = [
            family
            for family in ("fidelity", "security", "revocation")
            if not result[family]["passed"]
        ]
        hard += ["exact-semantics"] if result["quality"]["exact_semantics_failures"] else []
        log(
            f"[{name}] wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}; "
            f"hard failures: {hard or 'none'}"
        )
        status = status or (1 if hard else 0)
    if args.write_baseline:
        from benchmark.compare import baseline_subset

        results = {n: json.loads((out / f"results-{n}.json").read_text()) for n in args.scale}
        args.write_baseline.write_text(
            json.dumps(baseline_subset(results), indent=1, sort_keys=True) + "\n"
        )
        log(f"baseline written to {args.write_baseline}")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--scale", action="append", choices=sorted(SCALES), required=True)
    run_parser.add_argument("--out", type=Path, default=ROOT / "docs/evidence/M14")
    run_parser.add_argument("--keep", action="store_true")
    run_parser.add_argument("--write-baseline", type=Path)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--results", type=Path, action="append", required=True)
    baseline_parser = sub.add_parser("baseline")
    baseline_parser.add_argument("--results", type=Path, action="append", required=True)
    baseline_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "baseline":
        from benchmark.compare import baseline_subset

        results = {
            path.stem.removeprefix("results-"): json.loads(path.read_text())
            for path in args.results
        }
        args.out.write_text(json.dumps(baseline_subset(results), indent=1, sort_keys=True) + "\n")
        return 0
    baseline = json.loads(args.baseline.read_text())
    status = 0
    for path in args.results:
        report = compare(baseline, json.loads(path.read_text()))
        print(json.dumps(report, indent=1))
        status = status or (1 if report["hard_failures"] else 0)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
