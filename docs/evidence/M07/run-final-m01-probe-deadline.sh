#!/usr/bin/env bash
# Final named M01 probe. Run only after the D22 deadline-change 79-case gate and fixture CLI.
set -euo pipefail

cd /home/tux/personalbuild/c1

evidence_dir=docs/evidence/M07
log_path="$evidence_dir/final-m01-probe.log"
junit_path="$evidence_dir/final-m01-probe-junit.xml"
exit_path="$evidence_dir/final-m01-probe-exit.txt"

protected_paths=(
  docs/evidence/M01/inventory.json
  docs/evidence/M01/inventory.md
)
generated_paths=(
  "$evidence_dir/final-m01-generated-inventory.json"
  "$evidence_dir/final-m01-generated-inventory.md"
)

for path in "$log_path" "$junit_path" "$exit_path" "${generated_paths[@]}"; do
  if [[ -e "$path" || -L "$path" ]]; then
    printf 'Refusing to overwrite existing evidence: %s\n' "$path" >&2
    exit 73
  fi
done

for path in "${protected_paths[@]}"; do
  if [[ -L "$path" || ( -e "$path" && ! -f "$path" ) ]]; then
    printf 'Refusing to back up non-regular evidence path: %s\n' "$path" >&2
    exit 74
  fi
done

# Both earlier wrappers persist these records only after their work is terminal.
for status in pytest_exit tee_exit restore_exit script_exit; do
  if ! rg -qx -- "$status=0" "$evidence_dir/deadline-live-exit.txt"; then
    printf 'The D22 deadline-change live gate lacks successful terminal exit evidence.\n' >&2
    exit 75
  fi
done
if ! python3 - "$evidence_dir" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

evidence = Path(sys.argv[1])
try:
    tree = ET.parse(evidence / "deadline-live-junit.xml")
    suites = list(tree.iter("testsuite"))
    cases = list(tree.iter("testcase"))
    names = {(case.attrib["classname"], case.attrib["name"]) for case in cases}
    expected = json.loads((evidence / "corrected-live-expected-cases.json").read_text())
    actual_nodes = {f"{classname.replace('.', '/')}.py::{name}" for classname, name in names}
    passed = (
        sum(int(suite.attrib["tests"]) for suite in suites) == 79
        and len(cases) == len(names) == 79
        and all(classname and name for classname, name in names)
        and isinstance(expected, list)
        and all(isinstance(node, str) for node in expected)
        and len(expected) == len(set(expected)) == 79
        and actual_nodes == set(expected)
        and all(
            int(suite.attrib.get(key, "0")) == 0
            for suite in suites
            for key in ("errors", "failures", "skipped")
        )
        and not any(
            node.tag in {"failure", "error", "skipped"}
            for case in cases
            for node in case
        )
    )
except (OSError, ValueError, KeyError, ET.ParseError):
    passed = False
if not passed:
    raise SystemExit(1)
PY
then
  printf 'The shared-manifest JUnit evidence does not match all 79 expected passing cases.\n' >&2
  exit 75
fi
for status in child_returncode=0 cleanup_status=PASS wrapper_returncode=0; do
  if ! rg -qx -- "$status" "$evidence_dir/fixture-cli-exit.txt"; then
    printf 'The fixture CLI lacks successful terminal exit evidence.\n' >&2
    exit 75
  fi
done

mkdir -p "$evidence_dir"
backup_dir=$(mktemp -d)
declare -a backup_paths=()
declare -a existed_paths=()
for index in "${!protected_paths[@]}"; do
  path=${protected_paths[$index]}
  backup="$backup_dir/$index"
  if [[ -f "$path" ]]; then
    cp -p -- "$path" "$backup"
    existed_paths[$index]=1
  else
    existed_paths[$index]=0
  fi
  backup_paths[$index]=$backup
done

pytest_exit=NOT_RUN
tee_exit=NOT_RUN
script_exit=1
restore_exit=0

restore_evidence() {
  incoming_status=$?
  trap - EXIT
  set +e

  for index in "${!protected_paths[@]}"; do
    path=${protected_paths[$index]}
    backup=${backup_paths[$index]}
    generated=${generated_paths[$index]}
    changed=0
    if [[ "${existed_paths[$index]}" == 1 ]]; then
      if [[ ! -f "$path" ]] || ! cmp -s -- "$path" "$backup"; then
        changed=1
      fi
    elif [[ -e "$path" ]]; then
      changed=1
    fi

    # Never follow an unexpected symlink or copy an unexpected object on restore.
    if [[ -L "$path" || ( -e "$path" && ! -f "$path" ) ]]; then
      restore_exit=1
      continue
    fi

    if (( changed )); then
      if [[ -f "$path" ]]; then
        if [[ -e "$generated" || -L "$generated" ]] || ! cp -p -- "$path" "$generated"; then
          restore_exit=1
        fi
      fi
    fi

    if [[ "${existed_paths[$index]}" == 1 ]]; then
      if ! cp -p -- "$backup" "$path"; then
        restore_exit=1
      fi
    elif [[ -e "$path" ]] && ! rm -f -- "$path"; then
      restore_exit=1
    fi
  done

  if [[ "$pytest_exit" == NOT_RUN ]]; then
    script_exit=$incoming_status
  fi
  if (( restore_exit != 0 && script_exit == 0 )); then
    script_exit=1
  fi

  {
    printf 'pytest_exit=%s\n' "$pytest_exit"
    printf 'tee_exit=%s\n' "$tee_exit"
    printf 'restore_exit=%s\n' "$restore_exit"
    printf 'script_exit=%s\n' "$script_exit"
  } > "$exit_path"
  if (( $? != 0 )); then
    (( script_exit != 0 )) || script_exit=1
  fi

  if (( restore_exit == 0 )); then
    rm -rf -- "$backup_dir"
  else
    printf 'Inventory restoration failed; backups retained at %s\n' "$backup_dir" >&2
  fi
  exit "$script_exit"
}
trap restore_evidence EXIT

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
  uv run --locked pytest -s -m integration tests/integration/m01 \
    --tb=line \
    --show-capture=no \
    -p no:cacheprovider \
    -p tests.integration.m06.diagnostics \
    --junitxml="$junit_path" \
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
