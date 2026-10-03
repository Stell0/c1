#!/usr/bin/env bash
# M12 browser demonstration on disposable repositories, with all provider-key variables unset.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH
export C1_QUERY_TIME_BUDGET_MS=30000 C1_BACKEND_TIMEOUT_S=30

evidence_dir=docs/evidence/M12
env_path="$evidence_dir/makako-demo-env-check.txt"
demo_log="$evidence_dir/makako-demo.log"
exit_path="$evidence_dir/makako-demo-exit.txt"

unset_args=()
for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
  unset_args+=(-u "$name")
done

env "${unset_args[@]}" bash -c '
  status=0
  for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
    if [[ -n "${!name+x}" ]]; then printf "%s=SET\n" "$name"; status=1; else printf "%s=unset\n" "$name"; fi
  done
  printf "env_check_exit=%s\n" "$status"
  exit "$status"
' > "$env_path"

set +e
env "${unset_args[@]}" C1_STACK=1 PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache \
  systemd-inhibit --what=sleep:idle:handle-lid-switch --who=c1-m12-demo --why="M12 demo" --mode=block \
  uv run --locked python scripts/demo_m12.py > "$demo_log" 2> >(grep -v '"correlation_id"' > "$evidence_dir/makako-demo-stderr.log")
demo_exit=$?
set -e
printf 'demo_exit=%s\n' "$demo_exit" > "$exit_path"
exit "$demo_exit"
