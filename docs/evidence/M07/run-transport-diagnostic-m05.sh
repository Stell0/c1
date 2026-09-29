#!/usr/bin/env bash
# Prepared diagnostic only; execute after the lead reviews the hook and wrapper.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/transport-diagnostic-m05.log"
junit_path="$evidence_dir/transport-diagnostic-m05-junit.xml"
exit_path="$evidence_dir/transport-diagnostic-m05-exit.txt"
frames_path="$evidence_dir/transport-diagnostic-m05-frames.jsonl"

# Directory first, followed by each other M05 case exactly once (12 total).
test_paths=(
  tests/integration/m05/test_t01_directory.py::test_t01_directory_shared_identity_and_authorized_assertions
  tests/integration/m05/test_backend_fetch.py::test_backend_fetch_by_ids_and_historical_commit
  tests/integration/m05/test_t02_filters.py::test_t02_combined_filters_keyword_language_valid_time_and_recorded_order
  tests/integration/m05/test_t02_filters.py::test_t02_hidden_boundary_does_not_become_unbounded
  tests/integration/m05/test_t03_noninterference.py::test_t03_hidden_matching_entity_keyword_and_edges_are_noninterfering
  tests/integration/m05/test_t04_identity_m05.py::test_t04_identity_merge_and_undo_keep_current_binding
  tests/integration/m05/test_t05_cursors.py::test_t05_entity_cursor_pins_revision_and_rechecks_current_access
  tests/integration/m05/test_t05_cursors.py::test_t05_traversal_cursor_restarts_after_frontier_rescope
  tests/integration/m05/test_t06_limits.py::test_t06_limits_reject_oversized_page_depth_and_backend_query_text
  tests/integration/m05/test_t06_limits.py::test_t06_hidden_and_nonexistent_are_indistinguishable
  tests/integration/m05/test_t06_limits.py::test_t06_deadline_returns_503_without_partial_items
  tests/integration/m05/test_t07_views.py::test_t07_project_reference_narrows_without_copy_or_grant
)

for path in "$log_path" "$junit_path" "$exit_path" "$frames_path"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing diagnostic evidence: %s\n' "$path" >&2
    exit 73
  fi
done

mkdir -p "$evidence_dir"
pytest_exit=NOT_RUN
tee_exit=NOT_RUN
script_exit=1

record_exit() {
  incoming_status=$?
  trap - EXIT
  set +e
  if [[ "$pytest_exit" == NOT_RUN ]]; then
    script_exit=$incoming_status
  fi
  {
    printf 'pytest_exit=%s\n' "$pytest_exit"
    printf 'tee_exit=%s\n' "$tee_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } > "$exit_path"
  if (( $? != 0 )); then
    (( script_exit != 0 )) || script_exit=1
  fi
  exit "$script_exit"
}
trap record_exit EXIT

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
    -p c1_m07_transport_frames \
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
