"""Run the existing read-only timing helper with diagnostic FGA fanout 32.

This override exists only in this process. The production default remains 16;
the configured 2,000 ms query budget and authorization checks are unchanged.
Runtime.start is not called by the wrapped helper.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import c1.query.plan as query_plan  # noqa: E402

HELPER = ROOT / "docs/evidence/M07/entity-phase-probe.py"
OUTPUT = ROOT / "docs/evidence/M07/entity-phase-fga32.json"

if OUTPUT.exists():
    raise SystemExit("refusing to overwrite diagnostic evidence")

query_plan._FGA_CONCURRENCY = 32
sys.argv = [str(HELPER), "--output", str(OUTPUT)]
runpy.run_path(str(HELPER), run_name="__main__")
