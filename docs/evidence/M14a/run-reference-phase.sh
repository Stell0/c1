#!/usr/bin/env bash
# M14a: M13 reference phase on makako (OD5): stop the development stack, build the
# candidate image, run the reference-deployment acceptance tests (T01, T03-T06,
# T08) and the measured bounds (T07), then tear the reference deployment down
# and restart the development stack. AI provider variables are unset.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH UV_CACHE_DIR=.uv-cache
evidence=docs/evidence/M14a
for path in "$evidence/reference-integration.log" "$evidence/reference-junit.xml" \
            "$evidence/reference-exit.txt" "$evidence/bench.json"; do
  if [[ -e "$path" ]]; then echo "refusing to overwrite $path" >&2; exit 73; fi
done

unset_args=()
for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
  unset_args+=(-u "$name")
done

dev=(c1-dev_keycloak_1 c1-dev_openfga_1 c1-dev_terminusdb_1 c1-dev_postgres_1)
podman stop "${dev[@]}" >/dev/null 2>&1 || true

{
  printf 'started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  podman build -f deployment/reference/Containerfile -t localhost/c1:0.1.0rc1 . 2>&1 | tail -3
  podman image inspect localhost/c1:0.1.0rc1 --format 'image_id={{.Id}}'
  printf 'source_revision=%s\n' "$(git rev-parse HEAD)"
} > "$evidence/reference-image.txt"

set +e
env "${unset_args[@]}" C1_REFERENCE=1 PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" \
  systemd-inhibit --what=sleep:idle:handle-lid-switch --who=c1-m14a-reference --why="M14a reference phase" --mode=block \
  uv run --locked pytest -q -x --tb=short -p no:cacheprovider -p no:logging \
    --junitxml="$evidence/reference-junit.xml" tests/integration/m13 \
    > "$evidence/reference-integration.log" 2>&1
pytest_exit=$?
bench_exit=NOT_RUN
if [[ $pytest_exit -eq 0 ]]; then
  env "${unset_args[@]}" C1_REFERENCE=1 \
    uv run --locked python scripts/bench_m13.py --out "$evidence/bench.json" \
    > "$evidence/bench.log" 2>&1
  bench_exit=$?
fi
set -e

podman-compose -p c1-ref -f deployment/reference/compose.yaml down -v >/dev/null 2>&1 || true
for name in c1-dev_postgres_1 c1-dev_terminusdb_1 c1-dev_openfga_1 c1-dev_keycloak_1; do
  podman start "$name" >/dev/null 2>&1 || true
done
{
  printf 'pytest_exit=%s\n' "$pytest_exit"
  printf 'bench_exit=%s\n' "$bench_exit"
  printf 'finished_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$evidence/reference-exit.txt"
[[ $pytest_exit -eq 0 && $bench_exit == 0 ]]
