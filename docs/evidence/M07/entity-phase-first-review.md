# Read-only entity phase probe

One run made two authenticated read-only exact-label entity queries through
`runtime.query.entities`, using the configured 2,000 ms budget. The helper did
not call `Runtime.start`; it detected the installed registry and used the
existing dev-fixture token before timing. No query arguments, identity values,
records, headers, response bodies, credentials, or exception messages were
retained.

- Cold request: 503, `C1-QY-053`, 2,002.195 ms. Timed phases included query
  selection 1,184.485 ms, current binding index 397.102 ms, resource
  authorization 293.403 ms, query records 408.325 ms, and final authorization
  407.941 ms. A precise fallback fetch was also observed (228.043 ms).
- Warm request: 200, count 1, 1,396.833 ms. Query selection was 541.965 ms,
  current binding index 0.012 ms, resource authorization 266.039 ms, query
  records 392.929 ms, and final authorization 460.159 ms. A precise fallback
  fetch was observed (290.548 ms).

Instrumented phase durations overlap; they are not additive and do not alone
establish causation. These two observations are not a latency guarantee.

The actual run used the helper SHA-256
`d51708da6539f9b57fe6b683e09b7ebc18baff67e43278404a92d3f14d092917` and
command recorded in [`entity-phase-first.log`](entity-phase-first.log). The
generated JSON was preserved byte-for-byte as
[`entity-phase-first.json`](entity-phase-first.json); the helper's original
output filename remains available as
[`entity-phase-probe-guarded.json`](entity-phase-probe-guarded.json).
Pytest/API process exit was 0; see [`entity-phase-first-exit.txt`](entity-phase-first-exit.txt).

After the completed probe, the helper was changed only to let cancellation
and keyboard interrupts propagate instead of converting them into request
results. The final helper SHA-256 is
`56be4c03330eb7731285ad0cc0567918746f486ac1c3909ce99b5d9b0569312f`.
Final-helper static checks all exited 0:

- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked ruff check docs/evidence/M07/entity-phase-probe.py`
- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked ruff format --check docs/evidence/M07/entity-phase-probe.py`
- `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked mypy --strict docs/evidence/M07/entity-phase-probe.py`
