#!/usr/bin/env bash
# Run from the C1 checkout against the isolated, pinned supervisor fixtures.
set -euo pipefail
umask 077
unset OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY

c1_gate_root=$(git rev-parse --show-toplevel)
cd "$c1_gate_root"
export UV_CACHE_DIR="$c1_gate_root/.uv-cache"
export PLAYWRIGHT_BROWSERS_PATH="$c1_gate_root/.playwright"
export C1_CONTAINER_RUNTIME=docker C1_ENGINE=docker
export C1_COMPOSE=${C1_COMPOSE:-/tmp/c1-m14c-tools/docker-compose}
export COMPOSE="$C1_COMPOSE"
export C1_PROBE_ENV_FILE=${C1_PROBE_ENV_FILE:-/tmp/c1-m14c-dev/.env}
export C1_PROBE_TERMINUS_URL=http://127.0.0.1:17363
export C1_PROBE_FGA_URL=http://127.0.0.1:19080
export C1_PROBE_KEYCLOAK_URL=http://127.0.0.1:19090
export C1_DEV_TERMINUS_PORT=17363 C1_DEV_FGA_PORT=19080 C1_DEV_KEYCLOAK_PORT=19090
export C1_BACKEND_TIMEOUT_S=30 C1_FGA_DEADLINE=30s C1_QUERY_TIME_BUDGET_MS=30000
export C1_STACK=1 C1_BROWSER=1
c1_gate_output=${C1_GATE_OUTPUT:-/tmp/c1-m14c-final}
mkdir -p "$c1_gate_output"

case "${1:?Specify check, external, regression or reference}" in
  check)
    # Local checks intentionally do not establish real-service acceptance.
    env -u C1_STACK -u C1_BROWSER -u C1_EXTERNAL -u C1_REFERENCE make check
    ;;
  external)
    export C1_EXTERNAL=1
    flock /tmp/c1-m14c-dev-gate.lock uv run --locked pytest --assert=plain -q -s -x \
      --junitxml="$c1_gate_output/external.xml" tests/integration/m14c
    ;;
  regression)
    shift
    if [[ $# == 0 ]]; then
      set -- tests/integration/m01 tests/integration/m02 tests/integration/m03 \
        tests/integration/m04 tests/integration/m05 tests/integration/m06 \
        tests/integration/m07 tests/integration/m08 tests/integration/m09 \
        tests/integration/m09a tests/integration/m10 tests/integration/m11 \
        tests/integration/m12 tests/integration/m14b
    fi
    flock /tmp/c1-m14c-dev-gate.lock uv run --locked pytest --assert=plain -q -s -x \
      --junitxml="$c1_gate_output/regression.xml" "$@"
    ;;
  reference)
    export C1_REFERENCE=1
    export C1_REFERENCE_DIR=${C1_REFERENCE_DIR:-/tmp/c1-m14c-reference}
    export C1_REFERENCE_PROJECT=${C1_REFERENCE_PROJECT:-c1-m14c-reference}
    export C1_REF_NET_PREFIX=${C1_REF_NET_PREFIX:-10.89.241}
    unset C1_REFERENCE_REUSE
    # The harness tears down these projects and deletes its private fixtures.
    [[ "$C1_REFERENCE_PROJECT" == c1-m14c-* && "$C1_REFERENCE_DIR" == /tmp/c1-m14c-* ]]
    [[ -z $(docker ps -aq --filter label=com.docker.compose.project=c1-dr) ]]
    uv run --locked pytest --assert=plain -q -s -x \
      --junitxml="$c1_gate_output/reference.xml" tests/integration/m13
    ;;
  *) exit 2 ;;
esac
