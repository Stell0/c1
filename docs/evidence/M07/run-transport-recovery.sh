#!/usr/bin/env bash
# Prepared only. Execute after lead review and successful terminal M05 diagnostic.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
down_log="$evidence_dir/recovery-stack-down.log"
down_exit_path="$evidence_dir/recovery-stack-down-exit.txt"
up_log="$evidence_dir/recovery-stack-up.log"
up_exit_path="$evidence_dir/recovery-stack-up-exit.txt"

for path in "$down_log" "$down_exit_path" "$up_log" "$up_exit_path"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing recovery evidence: %s\n' "$path" >&2
    exit 73
  fi
done
for status in pytest_exit tee_exit script_exit; do
  if ! rg -qx -- "$status=0" "$evidence_dir/transport-diagnostic-m05-exit.txt"; then
    printf 'The M05 diagnostic lacks successful terminal exit evidence.\n' >&2
    exit 75
  fi
done

# stack-up must reuse the existing configuration rather than generate a new one.
if [[ ! -f deployment/.env || -L deployment/.env ]]; then
  printf 'Existing regular deployment configuration is required for recovery.\n' >&2
  exit 78
fi

# Exclusive descriptors prevent following a destination introduced after preflight.
set -o noclobber
exec 3>"$down_log" 4>"$up_log" 5>"$down_exit_path" 6>"$up_exit_path"
set +o noclobber

down_make_exit=NOT_RUN
down_tee_exit=NOT_RUN
down_step_exit=NOT_RUN
up_make_exit=NOT_RUN
up_tee_exit=NOT_RUN
up_step_exit=NOT_RUN
script_exit=1

record_exit() {
  incoming_status=$?
  trap - EXIT
  set +e
  if [[ "$down_make_exit" == NOT_RUN ]] || (( incoming_status != 0 && script_exit == 0 )); then
    script_exit=$incoming_status
  fi
  {
    printf 'make_exit=%s\n' "$down_make_exit"
    printf 'tee_exit=%s\n' "$down_tee_exit"
    printf 'step_exit=%s\n' "$down_step_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } >&5
  down_record_exit=$?
  {
    printf 'make_exit=%s\n' "$up_make_exit"
    printf 'tee_exit=%s\n' "$up_tee_exit"
    printf 'step_exit=%s\n' "$up_step_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } >&6
  up_record_exit=$?
  if (( down_record_exit != 0 || up_record_exit != 0 )); then
    (( script_exit != 0 )) || script_exit=1
  fi
  exit "$script_exit"
}
trap record_exit EXIT

# Existing stack-down retains volumes; stack reset and volume deletion are excluded.
set +e
env \
  -u OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY \
  -u HF_TOKEN \
  -u AZURE_OPENAI_API_KEY \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  make stack-down 2>&1 | tee >&3
pipe_status=("${PIPESTATUS[@]}")
down_make_exit=${pipe_status[0]:-125}
down_tee_exit=${pipe_status[1]:-125}
down_step_exit=$down_make_exit
if (( down_step_exit == 0 && down_tee_exit != 0 )); then
  down_step_exit=$down_tee_exit
fi
script_exit=$down_step_exit
if (( script_exit != 0 )); then
  exit "$script_exit"
fi

env \
  -u OPENAI_API_KEY \
  -u ANTHROPIC_API_KEY \
  -u GEMINI_API_KEY \
  -u GOOGLE_API_KEY \
  -u HF_TOKEN \
  -u AZURE_OPENAI_API_KEY \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  make stack-up 2>&1 | tee >&4
pipe_status=("${PIPESTATUS[@]}")
up_make_exit=${pipe_status[0]:-125}
up_tee_exit=${pipe_status[1]:-125}
up_step_exit=$up_make_exit
if (( up_step_exit == 0 && up_tee_exit != 0 )); then
  up_step_exit=$up_tee_exit
fi
script_exit=$up_step_exit
set -e
exit "$script_exit"
