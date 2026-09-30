"""Keep the shared TerminusDB system graph compact between live integration tests.

Every live case creates and drops isolated databases. Each create/drop adds a
layer to TerminusDB's ``_system`` graph, and every later request resolves its
database through that graph. Without compaction the layer stack grows across
runs and inflates every backend call, which pushed deadline-bound requests past
their unchanged budgets. Optimizing ``_system`` rolls layers up without changing
data. It runs after each test, so it never affects a test's own measurements.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest

from probes.config import environment
from tests.integration.software import software  # noqa: F401  (shared session fixture)

_TERMINUS_URL = "http://127.0.0.1:16363"


@pytest.fixture(autouse=True)
def _compact_terminus_system_graph() -> Iterator[None]:
    yield
    if os.environ.get("C1_STACK") != "1":
        return
    password = environment().get("C1_TERMINUS_PASSWORD")
    if not password:
        return
    with httpx.Client(timeout=60, trust_env=False) as client:
        response = client.post(
            _TERMINUS_URL + "/api/optimize/_system", auth=httpx.BasicAuth("admin", password)
        )
    # A failed compaction is an environment fault; surface it instead of hiding it.
    response.raise_for_status()
