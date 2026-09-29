#!/usr/bin/env bash
# Prepared D20 authority-prefetch first-cohort timing; execute only after lead review.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/makako-t04-timing.log"
junit_path="$evidence_dir/makako-t04-timing.junit.xml"
exit_path="$evidence_dir/makako-t04-timing.exit.txt"
timing_path="$evidence_dir/makako-t04-timing.json"

# Fresh profile-task overlap first cohort, not initial reuse; original M06-T04 regression and two-second request budgets.
test_paths=(
  tests/integration/m06/test_t04_historical_rescope.py::test_t04_rescoped_part_disappears_from_old_document_views
)

for path in "$log_path" "$junit_path" "$exit_path" "$timing_path"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing diagnostic evidence: %s\n' "$path" >&2
    exit 73
  fi
done

mkdir -p "$evidence_dir"
pytest_exit=NOT_RUN
tee_exit=NOT_RUN
script_exit=1

record_exit() {
  incoming_status=$?
  trap - EXIT
  set +e
  if [[ "$pytest_exit" == NOT_RUN ]]; then
    script_exit=$incoming_status
  fi
  {
    printf 'pytest_exit=%s\n' "$pytest_exit"
    printf 'tee_exit=%s\n' "$tee_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } > "$exit_path"
  if (( $? != 0 )); then
    (( script_exit != 0 )) || script_exit=1
  fi
  exit "$script_exit"
}
trap record_exit EXIT

set +e
env \
  -u OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY \
  -u HF_TOKEN \
  -u AZURE_OPENAI_API_KEY \
  C1_STACK=1 \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  PYTHONPATH="$PWD/docs/evidence/M07:$PWD" \
  systemd-inhibit --what=sleep:idle:handle-lid-switch --who=c1-m07-t04 --why="M06-T04 timing" --mode=block \
  uv run --locked pytest -q -x \
    --tb=line \
    --show-capture=no \
    -p no:cacheprovider \
    -p tests.integration.m06.diagnostics \
    -p c1_m07_t04_timing \
    --c1-t04-timing-output="$timing_path" \
    --junitxml="$junit_path" \
    "${test_paths[@]}" \
    2>&1 | tee "$log_path"
pipe_status=("${PIPESTATUS[@]}")
pytest_exit=${pipe_status[0]:-125}
tee_exit=${pipe_status[1]:-125}
script_exit=$pytest_exit
if (( script_exit == 0 && tee_exit != 0 )); then
  script_exit=$tee_exit
fi
set -e
exit "$script_exit"
