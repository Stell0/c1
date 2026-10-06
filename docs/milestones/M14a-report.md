# M14a — Performance hardening: execution report

**Gate:** VERIFIED

**Plan and authorization**
- Approved plan: [M14a](M14a.md). The owner approved the plan and the roadmap insertion on 2026-10-05, then the authorization-path changes ("Approve, with ADR + tests").
- Decisions: [ADR-0025](../decisions/ADR-0025-performance.md).

**Revisions**
- Implementation: `bcaf67b`, plus `27e4254`. `27e4254` changes only the M09a-T04 lookup budget test, to follow ADR-0025's derived read decisions; the product code of the two revisions is identical.
- Host: makako (4 vCPU DO-Regular, 7.5 GiB, Rocky Linux 9.8, rootful Podman 5.8.2).
- Image: both phases built the same image ID, `b9788b5a206e…`:
  - reference phase built from `bcaf67b` ([image](../evidence/M14a/reference-image.txt));
  - benchmark built from `27e4254` ([image](../evidence/M14a/image.txt)).

## Named checks

| Check | Evidence | Result |
|---|---|---|
| **M14a-T01 Equivalence:** full M01–M13 regression | `bash docs/evidence/M14a/run-makako-gate.sh` (attempt 3, revision `27e4254`): [log](../evidence/M14a/makako-live-integration.log), [JUnit](../evidence/M14a/makako-live-junit.xml), [exit](../evidence/M14a/makako-live-exit.txt), [case check](../evidence/M14a/case-check.json), [host](../evidence/M14a/makako-live-host-suspend.txt) | **PASS:** 119 passed in 15,591 s (4:19:51), pytest exit 0. The 119 cases equal the [expected list](../evidence/M14a/regression-expected-cases.json); none missing, duplicated or unexpected. No host suspend. The M07 goldens are unchanged. |
| T01: M13 reference phase (T01–T08) | `bash docs/evidence/M14a/run-reference-phase.sh` (revision `bcaf67b`): [log](../evidence/M14a/reference-integration.log), [JUnit](../evidence/M14a/reference-junit.xml), [exit](../evidence/M14a/reference-exit.txt) | **PASS:** 8 passed in 4,785 s; bench exit 0 |
| T01: M14 benchmark against `v1-makako` | `bash docs/evidence/M14a/run-benchmark.sh` (revision `27e4254`): [log](../evidence/M14a/integration.log), [JUnit](../evidence/M14a/junit.xml), [run log](../evidence/M14a/run.log), results [S](../evidence/M14a/results-S.json) / [M](../evidence/M14a/results-M.json), [compare](../evidence/M14a/compare-v1.json) | **PASS:** 6 passed in 17,541 s, pytest exit 0. Fidelity, security invariance (122 of 122 at S, 130 of 130 at M) and revocation are at 1.0, and there are no exact-semantics failures. `python -m benchmark compare --baseline benchmark/baselines/v1-makako.json` reports no hard failures, no quality changes and no performance warnings at S or M. The corpus manifests and gold equal M14's byte for byte. |
| **M14a-T02 Round-trip budgets** | `tests/unit/m14a`, `tests/integration/m09a/test_t04_counters.py` | **PASS** (`make check`, and the regression above) |
| **M14a-T03 Measured improvement** | The tables below, [`limits.md`](../operations/limits.md) (regenerated from [bench.json](../evidence/M14a/bench.json)) | **PASS:** two targets are met. The three missed targets are reported with their measured gap, as T03 allows; M14b addresses them. |
| **M14a-T04 No authorization cache** | ADR-0025. Unit tests `test_read_cache`, `test_derived_read`. M03, M06 and M09a freshness cases in the regression; M14-T04 revocation in the benchmark. | **PASS:** caches hold only content keyed by commit. Revocation and re-scope take effect on the next request. |

## Measured improvement (makako, medians)

| Measurement | M13 / M14 before | M14a | Target |
|---|---|---|---|
| Simple read at S (keyword, alias, label, valid-at, document, neighborhood) | 7.9 s (M14 attempt 1) → 3.2 s (attempt 2) | **2.4 s** | ≤ 2 s: **missed by 0.4 s** |
| Simple read at M | 6.6 s | **2.7 s** | — |
| OpenFGA requests per simple read, S / M | 57 / 163 | **22 / 60** | — |
| `graph-context` 64 KiB, S / M | 9.7 s / 21.1 s | **7.2 s / 8.2 s** | ≤ 6 s: **missed by 1.2 s** |
| Hidden twin modify (36 replaces), S / M | 244 s / 274 s | **50 s / 60 s** | ≤ 60 s: **met** |
| Hidden twin add (98 creates), S | 97 s | **63 s** | — |
| Corpus load, S / M | 436 s / 1,372 s | 368 s / 1,253 s | — |
| M13 bench B2 entity list (1,000 + 2,000 resources) | HTTP 503 (30 s budget) | **HTTP 200**, 9.4 s / 4.2 s / 4.0 s | no 503: **met** |
| M13 bench B3 (1,500 + 3,000 resources) | HTTP 503 | 21.3 s, some 503s; 5.3 s and 4.9 s with 200s | — |
| M13 bench single-create apply | 32.4 s | **30.6 s** | ≤ 5 s: **missed by 25.6 s** |
| M13 bench `graph-context` / `documentation-update` | 13.8 s / 13.4 s | 3.2 s / 3.3 s | — |
| Candidates over the limit (5,490 resources) | 503 `C1-QY-053` (budget exhausted first) | **422 `C1-QY-052`** (the declared limit) | — |

On the laptop the same S reads take 0.23 s. makako is about 10 times slower for the same calls. M14b's phase timing explains that gap, and the single-create apply cost, per phase.

## Attempts that are not gate evidence

**Regression attempt 1** ([`makako-attempt1-live-*`](../evidence/M14a/makako-attempt1-live-integration.log), at `bcaf67b`):
- It failed at M09a-T04 after 96 passed: 2 list-objects calls against a budget of 1.
- That is the intended effect of ADR-0025's derived read decisions. The test was updated in `27e4254`: at most 2 list-objects calls and 0 checks with a verified model.

**Regression attempt 2** ([`makako-attempt2-live-*`](../evidence/M14a/makako-attempt2-live-integration.log)) is **invalid:**
- My queue script matched the text `benchmark_exit=0` and started the regression during the reference phase, while the development stack was stopped.
- Its first case failed with connection refused after 5 seconds.

Attempt 3 is a full rerun, not a resume.

## Deviations and refinements

- **Dropped or deferred items** are recorded in the plan: B2, D4, B4 and C2. B3 was superseded by derived read decisions.
- **The benchmark ran with modified evidence files on makako.** `working_tree_modified` is `true` in its results: the tracked M12 and M13 evidence files and `limits.md` had been regenerated by earlier runs. No product code was modified.
- **`limits.md`** is regenerated from the M14a bench. `scripts/bench_m13.py` now names the bench file it was generated from.
- **Secret scan:** 105 false positives (SHA-256 digests and a commit ID) were added to `.secrets.baseline` with `is_secret: false` ([audit](../evidence/M14a/secret-audit.md)).

## Limitations

- Three targets are missed: simple reads at S, `graph-context`, and single-create apply.
- B3 still returns some 503s at 4,500 readable resources.
- One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

M14b (owner-approved 2026-10-06) is implemented. Its makako gate (T01–T05) runs next and is compared against these M14a numbers.
