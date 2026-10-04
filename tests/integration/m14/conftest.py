"""M14 session: one benchmark run per scale on fresh reference deployments (D1, D12)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from benchmark.__main__ import _run_scale
from tests.integration.m13 import reference as ref

ROOT = Path(__file__).resolve().parents[3]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m14/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if not ref.reference_enabled():
                item.add_marker(pytest.mark.skip(reason="M14 benchmark requires C1_REFERENCE=1"))


def scales() -> list[str]:
    return os.environ.get("C1_BENCH_SCALES", "S,M").split(",")


@pytest.fixture(scope="session")
def results() -> Iterator[dict[str, dict[str, Any]]]:
    for name in ref.AI_VARIABLES:
        assert name not in os.environ, "M14 requires AI provider variables unset"
    out = Path(os.environ.get("C1_BENCH_OUT", ROOT / "docs/evidence/M14"))
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "run.log").open("a")

    def log(message: str) -> None:
        log_file.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
        log_file.flush()

    values: dict[str, dict[str, Any]] = {}
    try:
        for name in scales():
            try:
                values[name] = asyncio.run(_run_scale(name, out, log))
            finally:
                ref.teardown()
            (out / f"results-{name}.json").write_text(
                json.dumps(values[name], indent=1, sort_keys=True) + "\n"
            )
            log(f"[{name}] results written")
        yield values
    finally:
        log_file.close()
