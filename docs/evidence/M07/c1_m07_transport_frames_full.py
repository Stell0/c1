"""Record safe integration failure frames into an explicitly selected evidence file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TextIO

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/evidence/M07"
OUTPUT = EVIDENCE / "transport-diagnostic-m05-frames.jsonl"
_HANDLE = pytest.StashKey[TextIO]()
_MAX_EXCEPTIONS = 32
_MAX_FRAMES = 128
_BACKENDS = {16363: "terminusdb", 18080: "openfga", 18090: "keycloak", 18000: "c1-loopback"}
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _write(config: pytest.Config, record: dict[str, object]) -> None:
    handle = config.stash[_HANDLE]
    handle.write(json.dumps(record, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--c1-m07-failure-frames",
        type=str,
        default=str(OUTPUT),
        help="new JSONL evidence file directly inside docs/evidence/M07",
    )


def pytest_configure(config: pytest.Config) -> None:
    target = Path(config.getoption("--c1-m07-failure-frames"))
    if not target.is_absolute():
        target = ROOT / target
    if (
        target.parent != EVIDENCE
        or target.parent.resolve() != EVIDENCE
        or target.suffix != ".jsonl"
        or target.is_symlink()
        or target.exists()
    ):
        raise pytest.UsageError(
            "failure frames require a new nonsymlink JSONL in docs/evidence/M07"
        )
    # Exclusive reservation precedes every test's setup and service/resource use.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    config.stash[_HANDLE] = os.fdopen(fd, "w", encoding="utf-8")
    _write(config, {"kind": "session_start"})


def _frame_locations(exc: BaseException) -> tuple[list[dict[str, object]], bool]:
    frames: list[dict[str, object]] = []
    traceback = exc.__traceback__
    while traceback is not None and len(frames) < _MAX_FRAMES:
        filename = Path(traceback.tb_frame.f_code.co_filename)
        try:
            name = str(filename.resolve().relative_to(ROOT))
        except ValueError:
            name = filename.name
        frames.append(
            {
                "filename": name,
                "function": traceback.tb_frame.f_code.co_name,
                "lineno": traceback.tb_lineno,
            }
        )
        traceback = traceback.tb_next
    return frames, traceback is not None


def _backend(exc: BaseException) -> dict[str, str] | None:
    if not isinstance(exc, httpx.RequestError):
        return None
    try:
        request = exc.request
    except RuntimeError:
        return None
    url = request.url
    if (
        request.method not in _METHODS
        or url.scheme != "http"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port not in _BACKENDS
    ):
        return None
    return {"method": request.method, "backend": _BACKENDS[url.port]}


def _exceptions(exc: BaseException) -> tuple[list[dict[str, object]], bool]:
    records: list[dict[str, object]] = []
    seen: set[int] = set()
    pending = [(exc, "raised")]
    while pending and len(records) < _MAX_EXCEPTIONS:
        current, relation = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        frames, truncated = _frame_locations(current)
        record: dict[str, object] = {
            "class": type(current).__name__,
            "relation": relation,
            "frames": frames,
            "frames_truncated": truncated,
        }
        backend = _backend(current)
        if backend is not None:
            record["request"] = backend
        records.append(record)
        # Include suppressed context: a cleanup failure may hide an earlier phase failure.
        if current.__context__ is not None:
            pending.append((current.__context__, "context"))
        if current.__cause__ is not None:
            pending.append((current.__cause__, "cause"))
        if isinstance(current, BaseExceptionGroup):
            pending.extend((child, "group_member") for child in reversed(current.exceptions))
    return records, bool(pending)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    if not item.path.is_relative_to(ROOT / "tests/integration") or call.excinfo is None:
        return
    exc = call.excinfo.value
    if isinstance(exc, (pytest.skip.Exception, pytest.xfail.Exception)):
        return
    records, truncated = _exceptions(exc)
    _write(
        item.config,
        {
            "kind": "failure_frames",
            "nodeid": item.nodeid,
            "phase": call.when,
            "exceptions": records,
            "exceptions_truncated": truncated,
        },
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _write(session.config, {"kind": "session_finish", "pytest_exit": int(exitstatus)})


def pytest_unconfigure(config: pytest.Config) -> None:
    handle = config.stash.get(_HANDLE, None)
    if handle is not None:
        handle.close()
