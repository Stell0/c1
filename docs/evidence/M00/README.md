# M00 evidence

These are local development-harness results, not product/service proofs.
`M00-report.md` is the gate of record; local and remote M00 checks are verified.

- `bootstrap.log`, `check.log`, `canary_fail.log`, `canary_reset.log`:
  commands, output and exact exit codes from the final local checks.
- `check_canary.log`: the deliberately failing assertion also fails `make check`.
- `versions.log`, `final_validation.log`: host-tool versions and final syntax,
  whitespace and implementation-manifest verification.
- `clean_start.log`: isolated working-tree snapshot, its Git tree ID, a new
  Python installation and environment, and bootstrap/check with the six named
  AI environment variables unset. The original working tree is not committed.
- `committed_clean_start.log`: `make clean-start` passed from implementation
  commit `3d50b59`, cloning tree `c909745703739778c347b07c5eb6da2e998fa648`.
- `ci_runs.log`, `ci_*.log`: remote run commands, revision, URLs and conclusions;
  only bootstrap/check steps are retained from the fetched job logs.
- `implementation.sha256`: exact checked source/configuration/document inputs;
  evidence files and the report itself are excluded to avoid circular hashes.
  Verify with `sha256sum -c docs/evidence/M00/implementation.sha256`.
- `dependencies.json`: installed package versions and inspected license-file
  SHA-256 values from distribution `RECORD`/metadata; also Hatchling, editables,
  and trove-classifiers from uv's isolated build cache. Reproduce package versions
  with `uv tree --locked`; locate license files with Python's
  `importlib.metadata.distribution(name).files` after `make bootstrap`.

## Secret-baseline audit, 2026-09-25

Two source-text findings and 26 license-hash findings were reviewed and marked `is_secret: false`:

| Path | Finding | Reason |
|---|---|---|
| `docs/milestones/M01.md` | Secret Keyword | Prose after `Secrets:` describes ignored environment files and scrubbed logs; it is not a credential. |
| `scripts/check_baseline.py` | Base64 High Entropy String | Publicly recorded source-document revision identifier, matching both baseline documents; it is not an authentication token. |
| `docs/evidence/M00/dependencies.json` | 26 Hex High Entropy String findings | SHA-256 digests of downloaded license/notice files. Each finding fingerprint was checked against the computed digest set; no credential values. |

No real credentials or blanket finding exclusions were added. Baseline hashes
are one-way fingerprints; baseline configuration and all non-fingerprint content
are scanned separately. Runtime synthetic keys are generated only in disposable
test directories. Scanner output in evidence never includes raw finding values.

## Early failures and corrections

Initial sandbox downloads failed DNS resolution; the same public downloads
succeeded with approved network access. Initial mypy module discovery reported
duplicate module names; explicit package bases and `mypy_path` fixed the src
layout. Ruff initially found long lines/import formatting; these were fixed.
An independent reviewer found a baseline-file scan blind spot, a detector-disable
bypass in baseline settings, and the plan's in-progress status contradiction.
These were corrected and regression-tested; the checker validates settings
against the pinned CLI's offline defaults before loading the baseline.
Transient checks during those edits are superseded by the final transcripts,
not counted as passing runs.
