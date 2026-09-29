# Entity timing helper request counters

Updated the timing-only helper to instrument the index preparation method
available on the runtime: it prefers `_prepare_after_head` and falls back to
`_snapshot_after_head`. Added per-run FGA request counters around
`runtime.fga._request`: started, completed, active (`current`), peak active,
and cancelled. The wrapper does not inspect or retain call arguments, paths,
headers, payloads, or responses. The current count is decremented in `finally`.

The diagnostic only changes instrumentation. It does not change the
production FGA concurrency setting, backend requests, query budget, or
authorization work. No live calls or tests were run for this helper revision.

Final helper SHA-256:
`cef4643fd526a4470932365a5af939902809e9d4af286da392596504acecd5e9`.

Static commands and results:
- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked ruff check docs/evidence/M07/entity-phase-probe.py` — exit 0.
- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked ruff format --check docs/evidence/M07/entity-phase-probe.py` — exit 0; already formatted.
- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked mypy --strict docs/evidence/M07/entity-phase-probe.py` — exit 0; no issues in one source file.
