#!/usr/bin/env bash
# Unchanged single-case replay of the D21 gate failure (M04-T06) with host-suspend evidence.
# Same pytest options and plugins as run-read-retry-live-gate.sh; only the selection differs.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
manifest="$evidence_dir/implementation-files-read-retry-audited.sha256"
log_path="$evidence_dir/m04-t06-rerun-integration.log"
junit_path="$evidence_dir/m04-t06-rerun-junit.xml"
exit_path="$evidence_dir/m04-t06-rerun-exit.txt"
frames_path="$evidence_dir/m04-t06-rerun-failure-frames.jsonl"
host_path="$evidence_dir/m04-t06-rerun-host-suspend.txt"
before_path="$evidence_dir/manifest-check-before-m04-t06-rerun.log"
after_path="$evidence_dir/manifest-check-after-m04-t06-rerun.log"

test_node=tests/integration/m04/test_t06_restore_security.py::test_t06_restore_cannot_resurrect_old_scope_access

for path in "$log_path" "$junit_path" "$exit_path" "$frames_path" "$host_path" "$before_path" "$after_path"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing evidence: %s\n' "$path" >&2
    exit 73
  fi
done

# Seconds the host has spent suspended since boot: CLOCK_BOOTTIME counts suspend, CLOCK_MONOTONIC does not.
suspended_seconds() {
  python3 -c 'import time; print(f"{time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC):.3f}")'
}

manifest_check() {
  env UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache \
    uv run --locked python "$evidence_dir/verify-manifest.py" "$manifest"
}

set +e
manifest_check > "$before_path" 2>&1
manifest_before_exit=$?
set -e
if (( manifest_before_exit != 0 )); then
  printf 'Source manifest check failed before the rerun; see %s\n' "$before_path" >&2
  exit 76
fi

{
  printf 'started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'suspended_seconds_since_boot_before=%s\n' "$(suspended_seconds)"
  printf '# journal suspend/resume lines since 2026-09-29 01:30 UTC (D21 gate window included):\n'
  journalctl --utc --since "2026-09-29 01:30:00" --no-pager -o short-iso 2>/dev/null \
    | grep -i -E "systemd-sleep|PM: suspend|PM: hibernat|Suspending system|System returned from sleep|Reached target.*[Ss]leep|Lid (closed|opened)" \
    || printf '# none found or journal not readable\n'
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
    "$test_node" \
    2>&1 | tee "$log_path"
pipe_status=("${PIPESTATUS[@]}")
pytest_exit=${pipe_status[0]:-125}
tee_exit=${pipe_status[1]:-125}

{
  printf 'finished_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'suspended_seconds_since_boot_after=%s\n' "$(suspended_seconds)"
} >> "$host_path"

manifest_check > "$after_path" 2>&1
manifest_after_exit=$?

script_exit=$pytest_exit
if (( script_exit == 0 && tee_exit != 0 )); then script_exit=$tee_exit; fi
if (( script_exit == 0 && manifest_after_exit != 0 )); then script_exit=76; fi

{
  printf 'pytest_exit=%s\n' "$pytest_exit"
  printf 'tee_exit=%s\n' "$tee_exit"
  printf 'manifest_before_exit=%s\n' "$manifest_before_exit"
  printf 'manifest_after_exit=%s\n' "$manifest_after_exit"
  printf 'script_exit=%s\n' "$script_exit"
} > "$exit_path"
exit "$script_exit"
