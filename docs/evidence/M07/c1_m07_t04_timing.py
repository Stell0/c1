"""Temporary timing-only plugin for M06-T04.

The original test behavior is unchanged except that the late-revocation
monkeypatch follows the actual history entrypoint.

No requests execute on import. Endpoint IDs, arguments, credentials, response
bodies, exception messages, and headers are never retained in the artifact.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_TEST = "tests/integration/m06/test_t04_historical_rescope.py"
_CODE = re.compile(r"C1-[A-Z]{2}-[0-9]{3}\Z")
_current: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "c1_m07_t04_request", default=None
)
_artifact: dict[str, Any] = {
    "diagnostic": "M06-T04 timing only; original test and two-second budget",
    "requests": [],
    "test_outcomes": [],
}
_started = time.monotonic()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--c1-t04-timing-output",
        required=True,
        help="New timing JSON path; existing files are never overwritten",
    )


def pytest_configure(config: pytest.Config) -> None:
    target = Path(config.getoption("--c1-t04-timing-output"))
    if target.exists():
        raise pytest.UsageError("T04 timing artifact already exists; choose a fresh path")


def _code(value: object) -> str | None:
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def _callsite() -> dict[str, Any] | None:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            if frame.f_code.co_filename.replace("\\", "/").endswith(_TEST):
                return {"file": _TEST, "line": frame.f_lineno}
            frame = frame.f_back
    finally:
        del frame
    return None


def _endpoint(path: str) -> str | None:
    clean = path.split("?", 1)[0]
    if not clean.startswith("/v1/documents/"):
        return None
    tail = clean[len("/v1/documents/") :].split("/")
    suffix = tail[-1] if len(tail) > 1 else ""
    if suffix not in {"", "history", "render", "parts", "export", "search"}:
        return None
    return "/v1/documents/{document_id}" + ("/" + suffix if suffix else "")


def _phase(original: Any, name: str) -> Any:
    @functools.wraps(original)
    async def timed(*args: Any, **kwargs: Any) -> Any:
        request = _current.get()
        if request is None:
            return await original(*args, **kwargs)
        started = time.monotonic()
        entry: dict[str, Any] = {
            "phase": name,
            "start_ms": round((started - request["_started"]) * 1000, 3),
        }
        try:
            value = await original(*args, **kwargs)
            entry["outcome"] = "ok"
            return value
        except BaseException as exc:
            entry["outcome"] = type(exc).__name__
            code = _code(getattr(exc, "code", None))
            if code is not None:
                entry["code"] = code
            raise
        finally:
            entry["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            request["phases"].append(entry)

    return timed


@pytest.fixture(autouse=True)
def _timing_hooks(request: pytest.FixtureRequest) -> Iterator[None]:
    if not request.node.nodeid.startswith(_TEST + "::"):
        yield
        return

    # Imports happen only when the selected test runs, never during plugin load.
    import c1.query.compile as compiler
    from c1.authorization.journal import Journal
    from c1.changes.history import HistoryService
    from c1.documents.service import DocumentsService
    from c1.query.index import CurrentBindingIndex
    from c1.query.plan import AuthorizedSelection
    from c1.query.service import QueryService
    from tests.integration.m03.conftest import LiveCase

    patch = pytest.MonkeyPatch()
    original_request = LiveCase.request

    @functools.wraps(original_request)
    async def timed_request(self: Any, method: str, path: str, **kwargs: Any) -> Any:
        endpoint = _endpoint(path) if method.upper() == "GET" else None
        if endpoint is None:
            return await original_request(self, method, path, **kwargs)
        started = time.monotonic()
        entry: dict[str, Any] = {
            "ordinal": len(_artifact["requests"]) + 1,
            "method": "GET",
            "endpoint": endpoint,
            "callsite": _callsite(),
            "start_ms": round((started - _started) * 1000, 3),
            "phases": [],
            "_started": started,
        }
        _artifact["requests"].append(entry)
        token = _current.set(entry)
        try:
            response = await original_request(self, method, path, **kwargs)
            entry["status"] = response.status_code
            if response.status_code >= 400:
                # Decode only to obtain a tightly allowlisted diagnostic code;
                # no response content is retained, rendered, or printed.
                try:
                    payload = response.json()
                    code = _code(payload.get("code")) if isinstance(payload, dict) else None
                    if code is not None:
                        entry["code"] = code
                except (ValueError, TypeError):
                    pass
            return response
        except BaseException as exc:
            entry["outcome"] = type(exc).__name__
            raise
        finally:
            entry["total_ms"] = round((time.monotonic() - started) * 1000, 3)
            entry["phases"].sort(key=lambda item: (item["start_ms"], item["phase"]))
            entry.pop("_started", None)
            _current.reset(token)

    try:
        patch.setattr(LiveCase, "request", timed_request)
        hooks = [
            (DocumentsService, "_selection", "document_selection"),
            (DocumentsService, "_history_manifest", "history_manifest"),
            (DocumentsService, "history", "document_history_total"),
            (QueryService, "selection", "authorization_selection"),
            (QueryService, "records", "authorized_fetch"),
            (QueryService, "historical_records", "historical_cohort_fetch"),
            (AuthorizedSelection, "finalize", "final_authorization"),
            (AuthorizedSelection, "finalize_after", "final_authorization_guarded"),
            (AuthorizedSelection, "_authorize", "fresh_resource_authorization"),
            (CurrentBindingIndex, "_snapshot_after_head", "current_binding_index"),
            (Journal, "head", "workflow_head"),
            (HistoryService, "metadata", "resource_history_metadata"),
            (compiler, "assert_installed_profiles", "fresh_profile_authority"),
            (compiler, "_graphql_chunk", "graphql_chunk"),
            (compiler, "_get_chunk", "precise_fallback_chunk"),
        ]
        for owner, attribute, label in hooks:
            patch.setattr(owner, attribute, _phase(getattr(owner, attribute), label))
        yield
    finally:
        patch.undo()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Iterator[None]:
    outcome: Any = yield
    report = outcome.get_result()
    if item.nodeid.startswith(_TEST + "::"):
        entry = {"test": item.nodeid, "phase": report.when, "outcome": report.outcome}
        crash = getattr(report.longrepr, "reprcrash", None) if report.failed else None
        if crash is not None:
            # Only the test source filename/line; exception messages are omitted.
            entry["failure_location"] = {"file": _TEST, "line": crash.lineno}
        _artifact["test_outcomes"].append(entry)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _artifact["pytest_exit"] = int(exitstatus)
    target = Path(session.config.getoption("--c1-t04-timing-output"))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing evidence from an earlier run.
    with target.open("x", encoding="utf-8") as output:
        json.dump(_artifact, output, indent=2, sort_keys=True)
        output.write("\n")
