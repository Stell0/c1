"""Benchmark configurations (M14 D10). Only the deterministic baseline exists.

Optional components are measured as ablations against the same gold data once
they are implemented; until then they are reported NOT_AVAILABLE, never as run.
"""

from __future__ import annotations

from typing import Any

CONFIGURATIONS: dict[str, dict[str, Any]] = {
    "deterministic": {
        "available": True,
        "reason": "C1 keyword, label, alias, valid-time, document and graph-context retrieval",
    },
    "semantic-seeds": {
        "available": False,
        "reason": "M15 Semantic Seed Index (optional) is not implemented",
    },
    "semantic-plus-gate": {
        "available": False,
        "reason": "M15 Semantic Seed Index and M16 Decision Gate are not implemented",
    },
    "hybrid-plus-gate-plus-graph": {
        "available": False,
        "reason": "M18 Adaptive hybrid context (needs M15, M16) is not implemented",
    },
}
