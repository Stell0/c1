#!/usr/bin/env bash
# M14 benchmark on makako: stop the development stack, build the candidate image,
# run T01-T06 (one fresh reference deployment per scale, S then M), then restart
# the development stack. AI provider variables are unset.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH UV_CACHE_DIR=.uv-cache
evidence=docs/evidence/M14
for path in "$evidence/integration.log" "$evidence/junit.xml" "$evidence/exit.txt" \
            "$evidence/results-S.json" "$evidence/results-M.json"; do
  if [[ -e "$path" ]]; then echo "refusing to overwrite $path" >&2; exit 73; fi
done

unset_args=()
for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
  unset_args+=(-u "$name")
done

dev=(c1-dev_keycloak_1 c1-dev_openfga_1 c1-dev_terminusdb_1 c1-dev_postgres_1)
podman stop "${dev[@]}" >/dev/null 2>&1 || true

version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
{
  printf 'started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  podman build -f deployment/reference/Containerfile -t "localhost/c1:$version" . 2>&1 | tail -3
  podman image inspect "localhost/c1:$version" --format 'image_id={{.Id}}'
  printf 'source_revision=%s\n' "$(git rev-parse HEAD)"
} > "$evidence/image.txt"

set +e
env "${unset_args[@]}" C1_REFERENCE=1 C1_BENCH_SCALES=S,M \
  systemd-inhibit --what=sleep:idle:handle-lid-switch --who=c1-m14 --why="M14 benchmark" --mode=block \
  uv run --locked pytest -q --tb=short -p no:cacheprovider -p no:logging \
    --junitxml="$evidence/junit.xml" tests/integration/m14 \
    > "$evidence/integration.log" 2>&1
pytest_exit=$?
set -e

podman-compose -p c1-ref -f deployment/reference/compose.yaml down -v >/dev/null 2>&1 || true
for name in c1-dev_postgres_1 c1-dev_terminusdb_1 c1-dev_openfga_1 c1-dev_keycloak_1; do
  podman start "$name" >/dev/null 2>&1 || true
done
{
  printf 'pytest_exit=%s\n' "$pytest_exit"
  printf 'finished_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$evidence/exit.txt"
exit "$pytest_exit"
