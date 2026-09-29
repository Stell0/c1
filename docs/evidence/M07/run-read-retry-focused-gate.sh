#!/usr/bin/env bash
# Focused read-retry M04 reviewed-apply and retry/crash gate (6 cases). Execute only after lead review.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/read-retry-focused-integration.log"
junit_path="$evidence_dir/read-retry-focused-junit.xml"
exit_path="$evidence_dir/read-retry-focused-exit.txt"
frames_path="$evidence_dir/read-retry-focused-failure-frames.jsonl"

# These two M04 files collect to six node IDs: one T01 and five T04 cases.
test_paths=(
  tests/integration/m04/test_t01_reviewed_apply.py
  tests/integration/m04/test_t04_retry_crash.py
)

protected_paths=(
  docs/evidence/M01/inventory.json
  docs/evidence/M01/inventory.md
  docs/evidence/M03/api.log
)
generated_paths=(
  "$evidence_dir/read-retry-focused-generated-m01-inventory.json"
  "$evidence_dir/read-retry-focused-generated-m01-inventory.md"
  "$evidence_dir/read-retry-focused-generated-m03-api.log"
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
  uv run --locked pytest -q -x \
    --tb=line \
    --show-capture=no \
    -p no:cacheprovider \
    -p tests.integration.m06.diagnostics \
    -p c1_m07_transport_frames_full \
    --c1-m07-failure-frames="$frames_path" \
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
