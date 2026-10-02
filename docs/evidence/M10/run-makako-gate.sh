#!/usr/bin/env bash
# M10 gate on makako: the M01–M09a 98-case selection plus tests/integration/m10 (104 cases); M09 D13 timeout settings.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH

evidence_dir=docs/evidence/M10
log_path="$evidence_dir/makako-live-integration.log"
junit_path="$evidence_dir/makako-live-junit.xml"
exit_path="$evidence_dir/makako-live-exit.txt"
frames_path="$evidence_dir/makako-live-failure-frames.jsonl"

# M08 86-case selection plus the 6 M09 cases = 92.
# Do not add the whole M06 directory: T04 is explicit and must occur only once.
test_paths=(
  tests/integration/m06/test_t04_historical_rescope.py::test_t04_rescoped_part_disappears_from_old_document_views
  tests/integration/m07
  tests/integration/m06/test_t01_ordered_views.py
  tests/integration/m06/test_t02_no_hidden_structure.py
  tests/integration/m06/test_t03_search_export.py
  tests/integration/m06/test_t05_content_integrity.py
  tests/integration/m06/test_t06_structure.py
  tests/integration/m06/test_t07_safe_rendering.py
  tests/integration/m01
  tests/integration/m02
  tests/integration/m03
  tests/integration/m04
  tests/integration/m05
  tests/integration/m08
  tests/integration/m09
  tests/integration/m09a
  tests/integration/m10
)

protected_paths=(
  docs/evidence/M01/inventory.json
  docs/evidence/M01/inventory.md
  docs/evidence/M03/api.log
)
generated_paths=(
  "$evidence_dir/makako-live-generated-m01-inventory.json"
  "$evidence_dir/makako-live-generated-m01-inventory.md"
  "$evidence_dir/makako-live-generated-m03-api.log"
)

for path in "$log_path" "$junit_path" "$exit_path" "$frames_path" "${generated_paths[@]}"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing evidence: %s\n' "$path" >&2
    exit 73
  fi
done

for path in "${protected_paths[@]}"; do
  if [[ -L "$path" || ( -e "$path" && ! -f "$path" ) ]]; then
    printf 'Refusing to back up non-regular evidence path: %s\n' "$path" >&2
    exit 74
  fi
done

mkdir -p "$evidence_dir"
backup_dir=$(mktemp -d)
declare -a backup_paths=()
declare -a existed_paths=()
for index in "${!protected_paths[@]}"; do
  path=${protected_paths[$index]}
  backup="$backup_dir/$index"
  if [[ -f "$path" ]]; then
    cp -p -- "$path" "$backup"
    existed_paths[$index]=1
  else
    existed_paths[$index]=0
  fi
  backup_paths[$index]=$backup
done

pytest_exit=NOT_RUN
tee_exit=NOT_RUN
script_exit=1
restore_exit=0

restore_evidence() {
  incoming_status=$?
  trap - EXIT
  set +e

  for index in "${!protected_paths[@]}"; do
    path=${protected_paths[$index]}
    backup=${backup_paths[$index]}
    generated=${generated_paths[$index]}
    changed=0
    if [[ "${existed_paths[$index]}" == 1 ]]; then
      if [[ ! -f "$path" ]] || ! cmp -s -- "$path" "$backup"; then
        changed=1
      fi
    elif [[ -e "$path" ]]; then
      changed=1
    fi

    # Fail restoration rather than follow an unexpected symlink/non-regular path.
    if [[ -L "$path" || ( -e "$path" && ! -f "$path" ) ]]; then
      restore_exit=1
      continue
    fi

    if (( changed )); then
      if [[ -f "$path" ]]; then
        if [[ -e "$generated" || -L "$generated" ]] || ! cp -p -- "$path" "$generated"; then
          restore_exit=1
        fi
      fi
    fi

    if [[ "${existed_paths[$index]}" == 1 ]]; then
      if ! cp -p -- "$backup" "$path"; then
        restore_exit=1
      fi
    elif [[ -e "$path" ]] && ! rm -f -- "$path"; then
      restore_exit=1
    fi
  done

  if [[ "$pytest_exit" == NOT_RUN ]]; then
    script_exit=$incoming_status
  fi
  if (( restore_exit != 0 && script_exit == 0 )); then
    script_exit=1
  fi

  {
    printf 'pytest_exit=%s\n' "$pytest_exit"
    printf 'tee_exit=%s\n' "$tee_exit"
    printf 'restore_exit=%s\n' "$restore_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } > "$exit_path"
  if (( $? != 0 )); then
    (( script_exit != 0 )) || script_exit=1
  fi

  if (( restore_exit == 0 )); then
    rm -rf -- "$backup_dir"
  else
    printf 'Evidence restoration failed; backups retained at %s\n' "$backup_dir" >&2
  fi
  exit "$script_exit"
}
trap restore_evidence EXIT

host_path="$evidence_dir/makako-live-host-suspend.txt"
suspended_seconds() {
  python3 -c 'import time; print(f"{time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC):.3f}")'
}
if [[ -e "$host_path" || -L "$host_path" ]]; then
  printf 'Refusing to overwrite existing evidence: %s\n' "$host_path" >&2
  exit 73
fi
{
  printf 'started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'suspended_seconds_since_boot_before=%s\n' "$(suspended_seconds)"
} > "$host_path"

set +e
env \
  -u OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY \
  -u HF_TOKEN \
  -u AZURE_OPENAI_API_KEY \
  C1_STACK=1 \
  C1_QUERY_TIME_BUDGET_MS=30000 \
  C1_BACKEND_TIMEOUT_S=30 \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  PYTHONPATH="$PWD/docs/evidence/M07:$PWD" \
  systemd-inhibit --what=sleep:idle:handle-lid-switch --who=c1-m10-gate --why="M10 regression gate" --mode=block \
  uv run --locked pytest -q -x \
    --tb=short \
    --show-capture=no \
    -p no:cacheprovider \
    -p tests.integration.m06.diagnostics \
    --junitxml="$junit_path" \
    "${test_paths[@]}" \
    2>&1 | tee "$log_path"
pipe_status=("${PIPESTATUS[@]}")
{
  printf 'finished_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'suspended_seconds_since_boot_after=%s\n' "$(suspended_seconds)"
} >> "$host_path"
pytest_exit=${pipe_status[0]:-125}
tee_exit=${pipe_status[1]:-125}
script_exit=$pytest_exit
if (( script_exit == 0 && tee_exit != 0 )); then
  script_exit=$tee_exit
fi
set -e
exit "$script_exit"
