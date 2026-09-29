# Diagnostic entity-query FGA fanout experiment

This one-process experiment set `c1.query.plan._FGA_CONCURRENCY` to 32 before
running the existing two-query timing helper. The production constant/default
remains 16; this does not change files under `src/`, the configured 2,000 ms
query budget, authorization checks, or the knowledge fetch behavior. The
helper did not call `Runtime.start`. This run measured two authorized reads,
not a sustained performance target.

- Launcher: [`entity-phase-fga32-probe.py`](entity-phase-fga32-probe.py),
  SHA-256 `7283493dafaaee5937c91cb4e11433c0db02b7a7d803a54e7c0e2c80da19647b`.
- Timing helper used: [`entity-phase-probe.py`](entity-phase-probe.py),
  SHA-256 `56be4c03330eb7731285ad0cc0567918746f486ac1c3909ce99b5d9b0569312f`.
- Exact launch command:
  `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY -u HF_TOKEN -u AZURE_OPENAI_API_KEY C1_STACK=1 UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked python docs/evidence/M07/entity-phase-fga32-probe.py`
- Exit: 0; see [`entity-phase-fga32.log`](entity-phase-fga32.log) and
  [`entity-phase-fga32-exit.txt`](entity-phase-fga32-exit.txt).
- Timing output: [`entity-phase-fga32.json`](entity-phase-fga32.json).

Both requests returned 200 with count 1. Cold took 1,939.104 ms; warm took
1,479.590 ms. Cold query selection took 1,061.663 ms, current binding index
384.750 ms, fresh authorization phases 295.358 and 362.621 ms, query-record
fetch 387.980 ms, and final authorization 487.983 ms. Warm selection took
616.917 ms, index 0.017 ms, fresh authorization phases 306.672 and 348.016 ms,
record fetch 382.758 ms, and final authorization 478.418 ms.

The previously recorded 16-concurrency control returned 503/C1-QY-053 on the
cold query at 2,002.195 ms and 200/count 1 on the warm query at 1,396.833 ms.
Its executed helper was the prior cancellation-handling revision
`d51708da6539f9b57fe6b683e09b7ebc18baff67e43278404a92d3f14d092917`; the
32-concurrency run used the final cancellation-safe helper SHA above. Phase
durations overlap, and a single pair per setting cannot establish causation or
a general latency result. This helper does not record peak simultaneous FGA
requests, so no observed concurrency ceiling is claimed.

The launcher passed scoped Ruff check, Ruff format check, and strict mypy; all
exited 0 before the run.
