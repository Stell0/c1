# ADR-0002 — Checks and truthful evidence

**Status:** accepted for M00 by the owner's implementation request, 2026-09-25.

## Context and decision

Use Ruff 0.16.9 for lint and formatting, mypy 2.3.1 in strict mode for source,
scripts and tests, pytest 9.0.2, and detect-secrets 1.5.0. `make check` runs the
same five check targets locally and in GitHub Actions. The marker package has no
runtime dependencies. Development licenses inspected from downloaded artifacts
are recorded in `docs/evidence/M00/dependencies.json`; MIT, BSD, Apache, PSF and
MPL-2.0 components are open-source development dependencies. Keep their notices
with installed artifacts; any future redistribution requires the M01/M13
inventory. `NOTICE` remains a project placeholder, not a complete vendor bundle.

The standard-library baseline checker verifies local file hashes, actual
requirement headings, extension attribution, roadmap/report claims, and the
bounded README inventory. Human review still determines semantic fidelity;
matching a hash does not establish equivalence to inaccessible cloud sources.

Secret checking enumerates tracked and nonignored untracked files with Git.
Unlike `detect-secrets scan`, the hook rejects findings with a nonzero exit.
All baseline findings must have been audited as false positives. Baseline JSON is
also scanned with default detectors, removing only validated SHA-1 fingerprint
fields to avoid recursive hash findings. Before loading baseline settings, the
checker compares its version, detectors, thresholds and filters with an empty-file
scan using the pinned CLI's offline defaults. A baseline edit cannot silently
disable a detector or add an exclusion. Configuration changes require deliberate
tooling review. The hook runs
offline with a temporary baseline; its exit 3 means only line offsets/removed
findings changed, so that result is accepted without modifying repository files.
New findings remain failures. Raw hook diagnostics are withheld from transcripts
because they can contain credential values. The test uses a disposable synthetic
AWS-style key, never a real credential.

CI pins checkout and setup-uv to immutable commits and disables persisted Git
credentials. Manual `canary_fail=true` makes the normal `make check` job fail;
false restores normal behavior. Remote failure and recovery have been exercised at implementation commit `3d50b59`; the M00 report links both runs.

## Evidence

Checked 2026-09-25:

- [Ruff configuration](https://docs.astral.sh/ruff/configuration/) and
  [mypy module mapping](https://mypy.readthedocs.io/en/stable/running_mypy.html#mapping-file-paths-to-modules)
  support the src layout, explicit package bases, and strict checks.
- [detect-secrets upstream](https://github.com/Yelp/detect-secrets/tree/v1.5.0)
  and the installed `detect_secrets/pre_commit_hook.py` distinguish detection
  (exit 1), success (0), and baseline maintenance (3). The pinned package's
  `LICENSE` is Apache-2.0, even though its metadata says `UNKNOWN`.
- [setup-uv v7 tag object](https://api.github.com/repos/astral-sh/setup-uv/git/tags/94527f2e458b27549849d47d273a16bec83a01e9)
  resolves to commit `37802adc94f370d6bfd71619e3f0bf239e1f3b78` (v7.6.0).
  [checkout v4 ref](https://api.github.com/repos/actions/checkout/git/ref/tags/v4)
  resolved to `11d5960a326750d5838078e36cf38b85af677262`.
- `docs/evidence/M00/` contains local transcripts; remote run results and links are recorded
  after the owner authorized the commit/push and verification step. The top-level Apache-2.0 text was
  downloaded from [Apache](https://www.apache.org/licenses/LICENSE-2.0.txt).

## Consequences and plan conflicts

The drafted M00-T04 rule demanded a VERIFIED report even for IN_PROGRESS/VERIFYING
roadmap rows, conflicting with W7 and the higher-priority roadmap workflow.
The implementation follows PLAN.md §2: only VERIFIED requires a VERIFIED report;
in-progress states do not claim completion. This corrects the plan conflict
without relaxing any completed-milestone evidence requirement. M00 remained BLOCKED
until the remote evidence was available.

The original M00 §8 permitted closing with CI NOT_RUN, but PLAN.md §2 and AGENTS.md §11 require
every named check. Those higher-priority requirements control: M00 could only be VERIFIED after remote CI passed.
No acceptance criterion is waived.

Default clean-start clones a clean committed repository. `--worktree` creates
and clones a disposable Git snapshot of nonignored working files; it never
commits or changes the real repository. This permits review before the owner
authorizes W8. Its evidence identifies a snapshot tree, not a published revision.
