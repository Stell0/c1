# Provisional-index read-only entity timing

The one read-only diagnostic run used the final timing helper SHA-256
`cef4643fd526a4470932365a5af939902809e9d4af286da392596504acecd5e9`. It
performed two exact-label entity queries with the configured 2,000 ms budget.
`Runtime.start` was not called. The instrumentation captured no call arguments,
paths, identities, records, headers, response bodies, credentials, or exception
messages.

- Command: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY -u HF_TOKEN -u AZURE_OPENAI_API_KEY C1_STACK=1 UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked python docs/evidence/M07/entity-phase-probe.py --output docs/evidence/M07/entity-phase-provisional-index.json`
- Exit: 0; see [`entity-phase-provisional-index.log`](entity-phase-provisional-index.log)
  and [`entity-phase-provisional-index-exit.txt`](entity-phase-provisional-index-exit.txt).
- Timing JSON: [`entity-phase-provisional-index.json`](entity-phase-provisional-index.json).

Both queries returned 200 with count 1. Cold took 1,813.570 ms; warm took
1,351.835 ms. Each run made 225 FGA requests: started 225, completed 225,
current 0 at end, peak concurrent 16, cancelled 0. These are counts from these
two requests, not a general load or latency guarantee.

Cold phases observed: selection 926.209 ms, current binding index preparation
214.143 ms, fresh resource authorization 252.282 ms, query-record fetch
374.521 ms, installed profile authority 150.172 ms, and final authorization
511.266 ms. Warm phases were selection 558.911 ms, index preparation 0.015 ms,
fresh authorization 252.400 ms, record fetch 380.725 ms, installed profile
authority 147.366 ms, and final authorization 410.785 ms. Phase durations
overlap; do not add them to estimate request time.

The current 345-input manifest was rechecked before the probe with all 345
hashes unchanged. The old 344-entry main manifest matched its preserved
`implementation-files-first-final-gate.sha256` copy exactly; the main manifest
was then refreshed from `implementation-files-provisional-index.sha256`.
`python3 docs/evidence/M07/verify-manifest.py` exited 0 and reported
`PASS: 345 frozen implementation inputs unchanged` in
[`manifest-check-before-corrected-live.log`](manifest-check-before-corrected-live.log).

The offline wheel build exited 0 and produced 117 entries, including the
expected context, topic, battery, and storage assets. No environment, evidence,
cache, or Python-cache paths were present. Its SHA-256 is
`1777fe25920584396d593020e7bb6bc94bc2660eb793d7207b157533cff1d4f3`; details
are in [`wheel-provisional-index-check.md`](wheel-provisional-index-check.md).
