# M00 — Baseline and development harness report

**Gate:** VERIFIED

**Approved plan revision:** `ffd65b9eb26b43911a1d1fb16c6e7b9a427d371d`, authorized for implementation by the owner on 2026-09-25. The explicit precedence corrections in M00 §9 are part of this working-tree change.
**Implementation revision:** `3d50b59a4392c679c6ab5bbc03fd338be6a06d3c`, committed and pushed to `origin/main` after owner authorization. Closure documentation/evidence is in the follow-up commit containing this report. [implementation.sha256](../evidence/M00/implementation.sha256) identifies the final reviewed inputs, excluding this report and generated evidence to avoid circular digests. Runtime code and dependencies are unchanged from the implementation commit.
**Report date:** 2026-09-25.

## Delivered scope

Python package marker, locked development/build dependencies, Make entry points,
lint/format/type/test checks, rejecting offline secret scan, baseline consistency
check, isolated clean-start helper, and pinned CI workflow. README, baseline
attribution/addendum, open choices, two ADRs, milestone templates, Apache-2.0
LICENSE and NOTICE are present. No API, backend service or later-milestone
implementation was added. The existing architecture editor swap file was preserved.

## Environment and evidence

Linux x86_64, CPython 3.13.14 (uv-managed), uv 0.12.2; pytest 9.0.2,
Ruff 0.16.9, mypy 2.3.1, detect-secrets 1.5.0, Hatchling 1.27.0.
[Dependency inventory](../evidence/M00/dependencies.json) records actual transitive
versions and inspected license-file hashes. `uv.lock` records development
artifact hashes; pyproject pins isolated build versions separately. Python 3.13's
patch selector may advance; the recorded test interpreter is 3.13.14.

The [evidence notes](../evidence/M00/README.md) explain the audited source-text and
license-hash false positives, initial failures and their fixes, and reproduction of the
inventory. Fixtures are local document copies and disposable synthetic secret
repositories. No prior milestone regression or protected request path exists.

## Commands and named checks

| Command | Exit | Result | Evidence |
|---|---:|---|---|
| `make bootstrap` | 0 | PASS | [bootstrap.log](../evidence/M00/bootstrap.log) |
| `make check` | 0 | PASS; lint, format, strict typing, 19 tests, secret and baseline checks | [check.log](../evidence/M00/check.log) |
| `C1_HARNESS_CANARY_FAIL=1 make test` | 2 | PASS for negative check: exactly the canary fails, 18 tests pass | [canary_fail.log](../evidence/M00/canary_fail.log) |
| `C1_HARNESS_CANARY_FAIL=1 make check` | 2 | PASS for negative check: aggregate gate fails | [check_canary.log](../evidence/M00/check_canary.log) |
| `make test` | 0 | PASS after removing the canary flag; 19 tests | [canary_reset.log](../evidence/M00/canary_reset.log) |
| `bash scripts/clean_start.sh --worktree` | 0 | PASS; fresh runtime/cache/environment in cloned disposable Git snapshot | [clean_start.log](../evidence/M00/clean_start.log) |
| `bash -n scripts/clean_start.sh` | 0 | PASS syntax check | [final_validation.log](../evidence/M00/final_validation.log) |
| `git diff --check` | 0 | PASS | [final_validation.log](../evidence/M00/final_validation.log) |
| `sha256sum -c docs/evidence/M00/implementation.sha256` | 0 | PASS input identity | [final_validation.log](../evidence/M00/final_validation.log) |
| `make clean-start` | 0 | PASS from committed checkout | [committed_clean_start.log](../evidence/M00/committed_clean_start.log) |
| `gh workflow run check.yml --ref main -f canary_fail=true` | Dispatch 0; CI check 2 | PASS negative check: exactly one intentional canary failure, 18 tests pass | [failure run](https://github.com/Stell0/c1/actions/runs/36153660154) |
| `gh workflow run check.yml --ref main -f canary_fail=false` | Dispatch 0; CI success | PASS: 19 tests and full gate | [recovery run](https://github.com/Stell0/c1/actions/runs/36153749620) |

| Named check | Result | Observation |
|---|---|---|
| M00-T01 Baseline fidelity | PASS for authoritative local baseline | Exact source hashes and requirement headings; extension attribution checked. Cloud equivalence is not claimed (see local-source override below). |
| M00-T02 Clean start | PASS | Bootstrap and all checks succeed in both the working-tree snapshot and the clean committed clone (tree `c909745703739778c347b07c5eb6da2e998fa648`) with the six named AI variables unset. |
| M00-T03 CI detects failure | PASS | Local and GitHub gates reject the canary and pass after reset; both remote runs target the same implementation revision. |
| M00-T04 No fabricated state | PASS | Only M00 is now marked VERIFIED, backed by this report; later milestones remain unimplemented. Integrity/state checks and documentation review pass. |
| M00-T05 Secret hygiene | PASS | Both direct detector and repository gate find a runtime-generated AWS-style key; tracked/untracked files, baseline contents and unaudited exceptions are covered; repository scan passes. |

Reproduce locally with `make bootstrap`, `make check`, the canary command above
(expected nonzero), then `make test`. Use `make clean-start` after a real clean
commit, or the explicit `--worktree` mode before it. The closure commit updates documentation and evidence only; the final input
manifest includes those documentation updates. Remote runs used the implementation
revision above, with unchanged harness code and dependencies. [versions.log](../evidence/M00/versions.log) records host tools.

## Source fidelity

The two root source files remain byte-identical to the approved baseline commit.
T01 verifies local hashes, F01–F10, A01–A22, G1–G9 headings, and separately
attributed extension references. The source documents' §0 local-source override
is authoritative. No independent cloud comparison or new owner attestation is
claimed; unavailable cloud credentials are not a prerequisite for this milestone.

## Review and decisions

An independent bounded reviewer found three material issues: the drafted T04 rule
rejected legitimate in-progress states, the initial secret wrapper omitted
the baseline file itself, and edited baseline settings could disable detectors.
The implementation now follows the higher-priority
PLAN.md workflow (VERIFIED requires a VERIFIED report) and scans baseline content
after removing only validated SHA-1 fingerprint fields. It compares baseline
version/detectors/thresholds/filters with the pinned CLI's offline defaults before
loading any baseline settings. Regression tests cover all three fixes. Template
gate spelling and the open-choice inventory were also aligned. The independent
reviewer reproduced the detector-disable attempt after the fix and confirmed it
is rejected, with no new finding in that bounded review. The lead validated the
integrated result: all 19 tests and the full local gate pass. Clean-start passed again
for the final inputs with a new Python installation, cache and environment. Remote CI evidence now proves the harness failure/recovery path. No product
capability is claimed.

`uv sync --frozen` alone does not enforce lock freshness; bootstrap now runs
`uv lock --check` first. No acceptance criterion was weakened. The M00 draft's
permission to close with CI NOT_RUN was corrected under PLAN.md §2 and AGENTS.md
§11: remote canary failure and restored pass remain required.

## Gate decision and bounded next action

All M00-T01–T05 checks pass within the authoritative local-source boundary.
The owner authorized commit/push after the implementation review. The automatic
[push run](https://github.com/Stell0/c1/actions/runs/36153623135) and manual recovery
run succeeded; the deliberate canary run failed solely at the expected assertion.
[ci_runs.log](../evidence/M00/ci_runs.log) records commands, revision and run URLs.
`make clean-start` passed from the committed repository with fresh Python/cache.
The independent closure review checked that all CI runs target the same commit
and that the committed clean-start tree matches it; no substantive gate issue
remained after refreshing the input manifest and roadmap next-action wording.
No unresolved local or remote M00 gate failure remains.

The next bounded action is owner selection of M01 and revalidation of its
provisional plan against this report. M01 is not started.
