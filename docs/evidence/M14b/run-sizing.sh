#!/usr/bin/env bash
# M14b D6 (OD3) on makako: the phase-timing probe on a fresh S deployment with the
# reference CPU caps, then with raised caps (same host, same image). The
# development stack is stopped for the run and restarted after it.
set -euo pipefail

cd /root/c1
export PATH=/root/c1/.tools:$PATH UV_CACHE_DIR=.uv-cache
evidence=docs/evidence/M14b
for path in "$evidence/sizing-default.json" "$evidence/sizing-raised.json" "$evidence/sizing.log"; do
  if [[ -e "$path" ]]; then echo "refusing to overwrite $path" >&2; exit 73; fi
done
unset_args=()
for name in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY; do
  unset_args+=(-u "$name")
done
dev=(c1-dev_keycloak_1 c1-dev_openfga_1 c1-dev_terminusdb_1 c1-dev_postgres_1)
podman stop "${dev[@]}" >/dev/null 2>&1 || true

status=0
run() {  # name, then CPU caps for C1, TerminusDB, OpenFGA, PostgreSQL
  local name=$1
  {
    printf '== %s c1=%s terminusdb=%s openfga=%s postgres=%s %s\n' "$name" "$2" "$3" "$4" "$5" "$(date -u +%FT%TZ)"
    env "${unset_args[@]}" C1_REFERENCE=1 C1_REF_C1_CPUS="$2" C1_REF_TERMINUSDB_CPUS="$3" \
      C1_REF_OPENFGA_CPUS="$4" C1_REF_POSTGRES_CPUS="$5" \
      systemd-inhibit --what=sleep:idle --who=c1-m14b-sizing --why="M14b sizing" --mode=block \
      uv run --locked python scripts/perf_probe.py prepare
    env "${unset_args[@]}" C1_REFERENCE=1 \
      uv run --locked python scripts/perf_probe.py measure --writes --out "$evidence/sizing-$name.json"
  } >> "$evidence/sizing.log" 2>&1 || status=1
}
set +e
run default 2 1.5 1 1
run raised 3 3 2 2
set -e
podman-compose -p c1-ref -f deployment/reference/compose.yaml down -v >/dev/null 2>&1 || true
for name in c1-dev_postgres_1 c1-dev_terminusdb_1 c1-dev_openfga_1 c1-dev_keycloak_1; do
  podman start "$name" >/dev/null 2>&1 || true
done
printf 'sizing_exit=%s finished_utc=%s\n' "$status" "$(date -u +%FT%TZ)" >> "$evidence/sizing.log"
exit "$status"
