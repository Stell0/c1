#!/usr/bin/env bash
# Run only after M07's corrected live T01-T07 gate has completed successfully.
# This preserves the prior 72-case M01-M06 selection and writes dedicated M07
# evidence without overwriting an earlier attempt.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/m01-m06-integration.log"
junit_path="$evidence_dir/m01-m06-junit.xml"

if [[ -e "$log_path" || -e "$junit_path" ]]; then
  printf 'Refusing to overwrite existing regression evidence: %s or %s\n' \
    "$log_path" "$junit_path" >&2
  exit 73
fi

mkdir -p "$evidence_dir"

if env \
  -u OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY \
  -u HF_TOKEN \
  -u AZURE_OPENAI_API_KEY \
  C1_STACK=1 \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  uv run --locked pytest -q \
    --tb=line \
    --show-capture=no \
    -p no:cacheprovider \
    -p tests.integration.m06.diagnostics \
    --junitxml="$junit_path" \
    tests/integration/m06 \
    tests/integration/m01 \
    tests/integration/m02 \
    tests/integration/m03 \
    tests/integration/m04 \
    tests/integration/m05 \
    2>&1 | tee "$log_path"; then
  test_status=0
else
  test_status=${PIPESTATUS[0]}
fi

printf 'pytest exit: %s\n' "$test_status" | tee -a "$log_path"
exit "$test_status"
