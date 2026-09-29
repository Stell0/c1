"""Diagnostic only: raise the live harness request budget to measure true latency.

Wraps the Settings class used by tests.integration.m03.conftest.live_case so each
live case gets C1_DIAG_QUERY_TIME_BUDGET_MS (default 30000). Source and assertions
are unchanged; results are measurements, not acceptance evidence.
"""

from __future__ import annotations

import functools
import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    import tests.integration.m03.conftest as harness

    budget = int(os.environ.get("C1_DIAG_QUERY_TIME_BUDGET_MS", "30000"))
    harness.Settings = functools.partial(harness.Settings, query_time_budget_ms=budget)  # type: ignore[misc]
