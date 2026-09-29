#!/usr/bin/env bash
# M08 demonstration with all provider-key variables unset: the producer
# (an idempotent rerun on an already-loaded instance), then the demo.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M08
env_path="$evidence_dir/demo-env-check.txt"
producer_log="$evidence_dir/demo-producer.log"
demo_log="$evidence_dir/demo.log"
exit_path="$evidence_dir/demo-exit.txt"

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
env "${unset_args[@]}" UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache \
  uv run --locked python scripts/software_producer.py --fixture software-integration > "$producer_log" 2>&1
producer_exit=$?
env "${unset_args[@]}" UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache \
  uv run --locked python scripts/demo_m08.py > "$demo_log" 2>&1
demo_exit=$?
set -e
printf 'producer_exit=%s\ndemo_exit=%s\n' "$producer_exit" "$demo_exit" > "$exit_path"
exit $(( producer_exit || demo_exit ))
