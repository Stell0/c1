#!/usr/bin/env bash
# Final M07 context demonstration with all provider-key variables unset.
# Run only after the D21 read-retry 79-case gate has terminal PASS evidence.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/final-context-demo.log"
env_path="$evidence_dir/final-context-demo-env-check.txt"
exit_path="$evidence_dir/final-context-demo-exit.txt"

for path in "$log_path" "$env_path" "$exit_path"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing evidence: %s\n' "$path" >&2
    exit 73
  fi
done

for status in pytest_exit tee_exit restore_exit script_exit; do
  if ! rg -qx -- "$status=0" "$evidence_dir/read-retry-live-exit.txt"; then
    printf 'The D21 read-retry live gate lacks successful terminal exit evidence.\n' >&2
    exit 75
  fi
done

provider_vars=(OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY)
unset_args=()
for name in "${provider_vars[@]}"; do unset_args+=(-u "$name"); done

# Prove, from inside the demo's environment, that no provider-key variable is set.
env "${unset_args[@]}" bash -c '
  status=0
  for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
    if [[ -n "${!name+x}" ]]; then printf "%s=SET\n" "$name"; status=1; else printf "%s=unset\n" "$name"; fi
  done
  printf "env_check_exit=%s\n" "$status"
  exit "$status"
' > "$env_path"

set +e
env "${unset_args[@]}" \
  UV_OFFLINE=1 \
  UV_CACHE_DIR=.uv-cache \
  uv run --locked python scripts/demo_m07.py 2>&1 | tee "$log_path"
pipe_status=("${PIPESTATUS[@]}")
demo_exit=${pipe_status[0]:-125}
tee_exit=${pipe_status[1]:-125}
set -e
{
  printf 'demo_exit=%s\n' "$demo_exit"
  printf 'tee_exit=%s\n' "$tee_exit"
} > "$exit_path"
if (( demo_exit != 0 )); then exit "$demo_exit"; fi
exit "$tee_exit"
