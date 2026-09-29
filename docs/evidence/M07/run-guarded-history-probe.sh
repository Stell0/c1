#!/usr/bin/env bash
# Original T04 assertions, with temporary phase timing and unchanged budgets.
set -euo pipefail
cd /home/tux/personalbuild/c1
evidence_dir=docs/evidence/M07
for suffix in .log .json -junit.xml -exit.txt; do
  if [[ -e "$evidence_dir/m06-t04-timing-guarded$suffix" ]]; then
    printf 'Refusing to overwrite guarded timing evidence\n' >&2
    exit 73
  fi
done
set +e
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY -u HF_TOKEN -u AZURE_OPENAI_API_KEY \
  C1_STACK=1 UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache \
  PYTHONPATH=docs/evidence/M07:src:. \
  uv run --locked pytest -q --tb=line --show-capture=no -p no:cacheprovider \
  -p tests.integration.m06.diagnostics -p c1_m07_t04_timing \
  --c1-t04-timing-output="$evidence_dir/m06-t04-timing-guarded.json" \
  --junitxml="$evidence_dir/m06-t04-timing-guarded-junit.xml" \
  tests/integration/m06/test_t04_historical_rescope.py::test_t04_rescoped_part_disappears_from_old_document_views \
  2>&1 | tee "$evidence_dir/m06-t04-timing-guarded.log"
statuses=("${PIPESTATUS[@]}")
printf 'pytest_exit=%s\ntee_exit=%s\n' "${statuses[0]}" "${statuses[1]}" \
  > "$evidence_dir/m06-t04-timing-guarded-exit.txt"
if (( statuses[0] != 0 )); then exit "${statuses[0]}"; fi
exit "${statuses[1]}"
