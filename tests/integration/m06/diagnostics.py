"""Print concise failure reports while a long-running M06 suite is running."""

from __future__ import annotations

import sys
from typing import Protocol

_MAX_FAILURE_CHARS = 8000


class _TestReport(Protocol):
    nodeid: str
    when: str
    failed: bool
    longreprtext: str


def pytest_runtest_logreport(report: _TestReport) -> None:
    """Write failed test reports directly to the console, bypassing capture."""
    if not report.failed:
        return

    details = report.longreprtext
    if len(details) > _MAX_FAILURE_CHARS:
        details = details[:_MAX_FAILURE_CHARS] + "\n...[truncated]"
    print(
        f"FAILED {report.nodeid} [{report.when}]\n{details}",
        file=sys.__stdout__,
        flush=True,
    )
