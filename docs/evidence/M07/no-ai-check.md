# M07 no-AI dependency check

PASS: mandatory project dependencies, `uv.lock`, pinned deployment compose, and environment template are unchanged. `pyproject.toml` adds only data-only package assets; no provider SDK/model configuration was added. Fixture load and real-service gate commands explicitly unset six provider variables; M07-T01 verifies their absence. Final live result is recorded separately. Projection/rendering use existing authorized records and fetch no source/provider content.
