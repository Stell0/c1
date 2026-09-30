"""M09 external consumer demonstration (D10): a deterministic, non-LLM client.

1. Requests the `test-development` package for `create_invoice` at {a1, b1}.
2. Checks that the reviewed, checked-in consumer test cites evidence present
   in the package's normative section (its header lists the part IDs).
3. Checks out a1 and a2 from the deterministic fixture repositories into a
   temporary directory and runs that test there with the pinned pytest,
   outside C1, with a minimal environment (no provider keys, no proxies).
4. Imports the two results as TestRuns through the `c1-svc-ci` producer.

C1 never runs code. This consumer runs only the checked-in fixture test and
fixture sources; it never runs anything taken from a C1 response.
Run after `scripts/software_producer.py --fixture software-integration`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import software_producer as sp  # noqa: E402

CONSUMER = sp.FIXTURE / "consumer" / "test_invoice_zero_amount_rejected.py"
EXPECTED = {"a1": "fail", "a2": "pass"}
ANCHOR = sp.symbol_id("ledger", "`ledger.api`/create_invoice().")


def cited_evidence() -> list[str]:
    """Part IDs the reviewed test declares it was written from."""
    return re.findall(r"^C1-evidence: (\S+)$", CONSUMER.read_text(encoding="utf-8"), re.MULTILINE)


async def fetch_package(loader: Any, actor: str) -> dict[str, Any]:
    body = {
        "profile": "test-development",
        "profile_version": "1",
        "anchor": {"id": ANCHOR},
        "target": {
            "snapshots": [sp.snapshot_id("a1"), sp.snapshot_id("b1")],
            "configurations": [sp.configuration_id("default")],
        },
        "goal": "conformance",
        "formats": ["structured"],
        "budget": {"unit": "bytes", "maximum": 524288},
    }
    units: list[dict[str, Any]] = []
    page = await loader.request("POST", "/v1/context", actor=actor, json_body=body)
    while True:
        if page.get("outcome") != "resolved":
            raise SystemExit(f"package not resolved: {page.get('outcome')}")
        for section in page["structured"]["sections"].values():
            units.extend(section)
        cursor = page["bounds"]["next_cursor"]
        if cursor is None:
            return {"revision": page["revision"], "units": units}
        page = await loader.request(
            "POST", "/v1/context", actor=actor, json_body={**body, "cursor": cursor}
        )


def _fixture_builder() -> Any:
    spec = importlib.util.spec_from_file_location("fixture_build", sp.FIXTURE / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_external(snapshots: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Run the reviewed test against each fixture snapshot, outside C1."""
    fixture = json.loads((sp.FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="c1-m09-consumer-") as directory:
        root = Path(directory)
        commits = _fixture_builder().build_repositories(root / "repos")
        for key in snapshots or sorted(EXPECTED):
            if commits[key]["commit"] != fixture["snapshots"][key]["commit"]:
                raise SystemExit(f"fixture commit for {key} is not reproducible")
            repository = root / "repos" / fixture["snapshots"][key]["repository"]
            archive = subprocess.run(
                ["git", "-C", str(repository), "archive", "--format=tar", commits[key]["commit"]],
                check=True,
                capture_output=True,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1"},
            ).stdout
            checkout = root / "checkout" / key
            checkout.mkdir(parents=True)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(checkout, filter="data")
            shutil.copyfile(CONSUMER, checkout / "tests" / CONSUMER.name)
            report = root / f"{key}.xml"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "-o",
                    "addopts=",
                    "--rootdir",
                    str(checkout),
                    "--junitxml",
                    str(report),
                    "tests/" + CONSUMER.name,
                ],
                cwd=checkout,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": str(root),
                    "PYTHONPATH": str(checkout),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "LC_ALL": "C.UTF-8",
                },
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode not in (0, 1) or not report.is_file():
                raise SystemExit(f"external runner failed on {key}: exit {completed.returncode}")
            result = sp.junit_result(report.read_bytes())
            results[key] = {"result": result, "report": sp.canonical_junit(report.read_bytes())}
    return results


async def consume(loader: Any, *, actor: str = "reviewer") -> dict[str, Any]:
    package = await fetch_package(loader, actor)
    normative = {unit["part_id"] for unit in package["units"] if unit["section"] == "normative"}
    cited = cited_evidence()
    missing = sorted(set(cited) - normative)
    if not cited or missing:
        raise SystemExit(f"consumer test cites evidence absent from the package: {missing}")
    results = await asyncio.to_thread(run_external)
    outcomes = {key: value["result"] for key, value in results.items()}
    if outcomes != EXPECTED:
        raise SystemExit(f"unexpected external results: {outcomes}")
    ci = await loader.whoami("ci")
    imported = [await sp.apply_run(loader, sp.consumer_case_run(ci))]
    for key, value in sorted(results.items()):
        run = sp.consumer_run(key, value["result"], value["report"], ci)
        imported.append(await sp.apply_run(loader, run))
    return {"cited": cited, "results": outcomes, "imported": imported}


async def _main() -> dict[str, Any]:
    from scripts.load_fixture import Loader, api_client

    async with api_client() as client:
        loader = await Loader.connect(client)
        return await consume(loader)


def main() -> None:
    print(json.dumps(asyncio.run(_main()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
