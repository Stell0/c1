"""Read-only timing helper for two fixed exact-label entity queries.

The artifact contains only run status, a safe result count, and phase timing.
It never stores query arguments, identities, response records, credentials,
headers, bodies, or exception messages. Runtime.start is deliberately omitted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from contextlib import ExitStack
from functools import wraps
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import c1.query.compile as compile_module  # noqa: E402
from c1.changes.profiles import detect_installed_registry  # noqa: E402
from c1.config import Settings  # noqa: E402
from c1.query.filters import LabelFilter, QueryFilters  # noqa: E402
from c1.runtime import Runtime  # noqa: E402
from probes.config import environment  # noqa: E402
from scripts.load_fixture import Loader  # noqa: E402

_QUERY_CODE = re.compile(r"C1-QY-[0-9]{3}\Z")
_active_run: dict[str, Any] | None = None


def _outcome(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if type(exc).__name__ == "QueryPlanError":
        return "QueryPlanError"
    if type(exc).__name__ == "BackendError":
        return "BackendError"
    return "error"


def _code(exc: BaseException) -> str | None:
    value = getattr(exc, "code", None)
    return value if isinstance(value, str) and _QUERY_CODE.fullmatch(value) else None


def _timed(original: Any, phase: str) -> Any:
    @wraps(original)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        run = _active_run
        if run is None:
            return await original(*args, **kwargs)
        started = time.monotonic()
        event: dict[str, Any] = {
            "phase": phase,
            "start_ms": round((started - run["started"]) * 1000, 3),
        }
        try:
            value = await original(*args, **kwargs)
            event["outcome"] = "ok"
            return value
        except BaseException as exc:
            event["outcome"] = _outcome(exc)
            code = _code(exc)
            if code is not None:
                event["code"] = code
            raise
        finally:
            event["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            run["phases"].append(event)

    return wrapper


def _instrument(stack: ExitStack, owner: Any, attribute: str, phase: str) -> None:
    original = getattr(owner, attribute)
    stack.enter_context(patch.object(owner, attribute, _timed(original, phase)))


async def _run(runtime: Runtime, principal: Any, name: str) -> dict[str, Any]:
    global _active_run
    started = time.monotonic()
    counts = {"started": 0, "completed": 0, "current": 0, "peak": 0, "cancelled": 0}
    run: dict[str, Any] = {
        "run": name,
        "started": started,
        "phases": [],
        "fga_request_counts": counts,
    }
    _active_run = run
    result: dict[str, Any] = {"run": name}
    try:
        response = await runtime.query.entities(
            principal, QueryFilters(label=LabelFilter(text="Tesla"))
        )
        result["status"] = 200
        count = response.get("count")
        if type(count) is int and count >= 0:
            result["count"] = count
        result["outcome"] = "ok"
    except Exception as exc:
        status = getattr(exc, "status", None)
        if type(status) is int and 400 <= status <= 599:
            result["status"] = status
        result["outcome"] = _outcome(exc)
        code = _code(exc)
        if code is not None:
            result["code"] = code
    finally:
        result["total_ms"] = round((time.monotonic() - started) * 1000, 3)
        phases = run["phases"]
        phases.sort(key=lambda event: (event["start_ms"], event["phase"]))
        result["phases"] = phases
        result["fga_request_counts"] = counts.copy()
        _active_run = None
    return result


def _instrument_fga_requests(stack: ExitStack, fga: Any) -> None:
    original = fga._request

    @wraps(original)
    async def counted(*args: Any, **kwargs: Any) -> Any:
        run = _active_run
        if run is None:
            return await original(*args, **kwargs)
        counts = run["fga_request_counts"]
        counts["started"] += 1
        counts["current"] += 1
        counts["peak"] = max(counts["peak"], counts["current"])
        try:
            value = await original(*args, **kwargs)
        except asyncio.CancelledError:
            counts["cancelled"] += 1
            raise
        except BaseException:
            counts["completed"] += 1
            raise
        else:
            counts["completed"] += 1
            return value
        finally:
            counts["current"] -= 1

    stack.enter_context(patch.object(fga, "_request", counted))


async def _collect() -> dict[str, Any]:
    for key, value in environment().items():
        os.environ.setdefault(key, value)
    runtime = Runtime(Settings.from_env())
    try:
        if runtime.settings.query_time_budget_ms != 2000:
            raise RuntimeError("configured query budget is not 2000 ms")
        runtime.registry = await detect_installed_registry(runtime.knowledge)
        token = await Loader(None, {}).user_token("dave")  # type: ignore[arg-type]
        principal = await runtime.tokens.authenticate(token)

        results: list[dict[str, Any]] = []
        with ExitStack() as stack:
            hooks = (
                (runtime.query, "selection", "query_selection"),
                (runtime.query, "records", "query_records"),
                (runtime.query.planner, "_authorize", "fresh_resource_authorization"),
                (runtime.query.planner, "finalize", "final_authorization"),
                (runtime.knowledge, "head", "knowledge_head"),
                (runtime.journal, "head", "workflow_head"),
                (
                    compile_module,
                    "assert_installed_profiles",
                    "installed_profile_authority",
                ),
                (compile_module, "_graphql_chunk", "graphql_chunk"),
                (compile_module, "_get_chunk", "precise_fallback_chunk"),
            )
            for owner, attribute, phase in hooks:
                _instrument(stack, owner, attribute, phase)
            index = runtime.query.planner.index
            index_method = (
                "_prepare_after_head"
                if hasattr(index, "_prepare_after_head")
                else "_snapshot_after_head"
            )
            _instrument(stack, index, index_method, "current_binding_index")
            _instrument_fga_requests(stack, runtime.fga)
            results.append(await _run(runtime, principal, "cold"))
            results.append(await _run(runtime, principal, "warm"))
        return {
            "diagnostic": "two read-only exact-label entity queries; timings only",
            "configured_budget_ms": runtime.settings.query_time_budget_ms,
            "runs": results,
        }
    finally:
        await runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new JSON artifact path; existing paths are never overwritten",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output path already exists; select a fresh path")
    if not args.output.parent.is_dir():
        parser.error("output directory must already exist")
    result = asyncio.run(_collect())
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(
        json.dumps(
            {
                "configured_budget_ms": result["configured_budget_ms"],
                "runs": [
                    {
                        key: run[key]
                        for key in (
                            "run",
                            "status",
                            "outcome",
                            "count",
                            "total_ms",
                            "fga_request_counts",
                        )
                        if key in run
                    }
                    for run in result["runs"]
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
