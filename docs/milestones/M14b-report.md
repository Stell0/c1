# M14b — Performance hardening, part 2: execution report

**Gate:** VERIFIED. T01–T04 pass. T05 passes by its alternative condition: the M14a latency targets are **not** met on makako, and the measured gap is reported per phase below.

**Plan and decisions**
- Approved plan: [M14b](M14b.md). The owner approved the plan and OD1–OD4 on 2026-10-06 ("I approve all of 4 optional improvements").
- Decisions: [ADR-0026](../decisions/ADR-0026-performance-part-2.md).

**Revisions**
- Implementation: `52e3c9e`…`36b2f92`, plus two fixes found by the gate:
  - `2e0b331`: `journal.list` of a moved record kind;
  - `fb85979`: the M11-T04 test.
- The regression ran at `fb85979`.
- The reference phase, benchmark and sizing ran at `36b2f92`. Its product code differs from `fb85979` only in `2e0b331`. That change touches only `Journal.list`/`list_many` for the moved kinds. No product path lists those kinds; product code reads them by ID only. The test that exposed the defect (M04-T01) lists one, and it passed in the regression at `fb85979`.

Host: makako (4 vCPU, 7.5 GiB, Rocky Linux 9.8, rootful Podman 5.8.2). Images: reference `49fde87fe846…`, benchmark `42d168d16b69…`, both built from `36b2f92` ([1](../evidence/M14b/reference-image.txt), [2](../evidence/M14b/image.txt)).

## Named checks

| Check | Evidence | Result |
|---|---|---|
| **M14b-T01 Equivalence:** full regression (M01–M12, M14b; 122 cases) | `bash docs/evidence/M14b/run-makako-gate.sh`, attempt 3 at `fb85979`: [log](../evidence/M14b/makako-live-integration.log), [JUnit](../evidence/M14b/makako-live-junit.xml), [exit](../evidence/M14b/makako-live-exit.txt), [case check](../evidence/M14b/case-check.json), [host](../evidence/M14b/makako-live-host-suspend.txt) | **PASS:** 122 passed in 15,599 s (4:19:58), pytest exit 0. The cases equal the [expected list](../evidence/M14b/regression-expected-cases.json). No host suspend. The M07 goldens are unchanged. |
| T01: M14 benchmark against `v1-makako` | `bash docs/evidence/M14b/run-benchmark.sh`: [log](../evidence/M14b/integration.log), [JUnit](../evidence/M14b/junit.xml), [run log](../evidence/M14b/run.log), results [S](../evidence/M14b/results-S.json) / [M](../evidence/M14b/results-M.json), [compare](../evidence/M14b/compare-v1.json) | **PASS:** 6 passed in 17,234 s. Fidelity, security invariance (122 of 122 at S, 130 of 130 at M) and revocation are at 1.0, with no exact-semantics failures. Compare: no hard failures, no quality changes, no performance warnings at S or M. The corpus and gold equal M14's byte for byte. |
| **M14b-T02 Freshness** | `tests/integration/m14b/test_t02_freshness.py` (in the regression); `tests/unit/m14b/test_finalize_changes.py` | **PASS:** OpenFGA tuples are changed directly (no journal write) between build and finalize. A reader removal, a re-binding and a group-membership removal each force the fresh path and a restart. An unrelated change takes the fresh path, and the read still succeeds. An unchanged store uses one OpenFGA call in finalize. The startup change-log probe is verified; on the pinned image, horizon 1 min → unverified, horizon 0 → verified. |
| **M14b-T03 Journal migration** | `tests/integration/m14b/test_t03_journal_migration.py` (regression); `bash docs/evidence/M14b/run-reference-phase.sh`: [log](../evidence/M14b/reference-integration.log), [JUnit](../evidence/M14b/reference-junit.xml), [exit](../evidence/M14b/reference-exit.txt) | **PASS:** a legacy journal migrates. Every payload stays reachable, and a second run moves nothing. The reference phase (M13 T01–T08, including backup, knowledge-only restore and disaster recovery) passed 8 of 8 on journals in the new layout. The makako dev stack's existing journal migrated during bootstrap. |
| **M14b-T04 History equivalence** | `tests/integration/m14b/test_t04_history_index.py` (regression); `scripts/history_equivalence.py` (laptop, M14 corpus S) | **PASS:** indexed history equals TerminusDB history across creates, replaces and a ChangeSet restore. A provisioned resource uses the fallback. On the S corpus, 60 of 60 sampled resources were identical (commit, timestamp, message, order). |
| **M14b-T05 Measured improvement** | Tables below; [sizing](../evidence/M14b/sizing.log) ([default](../evidence/M14b/sizing-default.json), [raised](../evidence/M14b/sizing-raised.json)); [bench.json](../evidence/M14b/bench.json) → [`limits.md`](../operations/limits.md) | **PASS (gap reported):** writes, loads, memory and backend calls improved. Simple reads, `graph-context` and single-create apply missed their targets; see the per-phase gap below. |

## Results (makako; M14a → M14b; medians)

| Measurement | M14a | M14b | Target |
|---|---|---|---|
| Simple read at S / M | 2.4 s / 2.7 s | 2.4 s / 2.7 s | ≤ 2 s at S: **missed** |
| OpenFGA requests per simple read, S / M | 22 / 60 | **13 / 32** | — |
| `graph-context` 64 KiB, S / M | 7.3 s / 8.3 s | 7.4 s / 8.1 s | ≤ 6 s: **missed** |
| OpenFGA requests per `graph-context`, S / M | 66 / 180 | **39 / 96** | — |
| Corpus load, S / M | 368 s / 1,253 s | **240 s / 794 s** | — |
| Hidden twin add (98 / 104 creates), S / M | 63 s / 77 s | **44 s / 49 s** | — |
| Hidden twin modify (36 / 38 replaces), S / M | 50 s / 60 s | **45 s / 50 s** | ≤ 60 s: met |
| C1 memory peak, S / M | 165 / 290 MiB | **123 / 177 MiB** | — |
| M13 bench apply, 50 / 200 operations | 49.7 s / 105.6 s | **33.7 s / 52.2 s** | — |
| M13 bench single-create apply | 30.6 s | 30.9 s | ≤ 5 s: **missed** |
| M13 bench B2 entity list | 200, 9.4 s | 200, 9.0 s | no 503: met |
| M13 bench B3 | some 503s | some 503s (first repeat), then 4.1–4.6 s | — |

On the laptop, the same probe (S corpus) improved more:
- simple read 0.23 → 0.20 s (13 OpenFGA calls);
- `/v1/history` 6.8 → 1.1 s;
- 97-create apply 18.2 → 7.9 s;
- 36-replace apply 7.5 → 4.9 s;
- corpus load 172 → 69 s.

The per-phase breakdown is in ADR-0026.

### Per-phase gap on makako (sizing probe, warm simple read, about 2.35 s)

| Phase | makako | laptop |
|---|---|---|
| `plan.build` (includes the binding source, about 95 ms) | 180–200 ms | 65–100 ms |
| `query.fetch` (includes schema authority) | 155–200 ms | 50–90 ms |
| `plan.finalize` | **1,450–1,990 ms** | 63–70 ms |
| Context render (64 KiB) | 480–500 ms | 130 ms |

- **Finalize dominates on makako.** During a request it makes three backend calls: two workflow head reads (TerminusDB) and one change-log read (OpenFGA).
  - In isolation on the same host and the same S deployment ([diagnosis](../evidence/M14b/diagnosis.txt)), a head read takes about 70 ms and the change-log read about 5 ms.
  - The request's TerminusDB time is about 2.4 s over 10 calls; the OpenFGA time is about 105 ms over 13 calls.
  - So the gap is in TerminusDB head reads made from within a request. The cause is **not identified**. Candidates are the 1-second connection keep-alive expiry (an M09a owner decision; plan item D8) and server-side behavior after the preceding GraphQL fetch.
  - A refused 8 KiB context, which skips finalize, takes 0.72 s.
- **D6 sizing: no gain from raising the caps,** so the reference defaults are kept (OD3). Raising C1 2 → 3 CPUs, TerminusDB 1.5 → 3, OpenFGA 1 → 2 and PostgreSQL 1 → 2 left warm reads at 2.33–2.42 s (2.33–2.40 s at the defaults). The remaining cost is not CPU contention.
- **Optimize** cut the workflow listing from 483 ms to 291 ms right after the S load. Head reads were unchanged.

## Attempts that are not gate evidence

**Regression attempt 1** ([`makako-attempt1-live-*`](../evidence/M14b/makako-attempt1-live-integration.log), at `36b2f92`):
- It failed at M04-T01 after 54 passed: `journal.list("ApplyReceipt")` returned nothing.
- The cause was a D4 defect. The moved kinds were no longer listed, although test code lists them.
- Fixed in `2e0b331`: listing a moved kind also lists the record class, at the same data version, retried if a write lands in between. A unit test was added.

**Regression attempt 2** ([`makako-attempt2-live-*`](../evidence/M14b/makako-attempt2-live-integration.log), at `2e0b331`):
- It failed at M11-T04 after 107 passed.
- The test compared whole document-history responses, including the serving knowledge head, which the accepted draft necessarily advances. The history entries were identical.
- It fails the same way on the laptop at the M14a revision `27e4254`. The likely reason it passed on makako before: both requests returned the same error body.
- Fixed in `fb85979` (test only): both requests must succeed, the head must advance, and everything else must be unchanged.

Attempt 3 is a full rerun, not a resume.

## Deviations and refinements

- **Change-log probe (added during the gate, `36b2f92`).** The makako dev OpenFGA had been created without `OPENFGA_CHANGELOG_HORIZON_OFFSET=0`. C1 now proves at startup that the change log shows writes immediately, and keeps the D3 shortcut off otherwise (ADR-0026).
- **Migration guard.** The plan asked for a migration that refuses to run while an operation is pending. The guard is the startup order instead: the migration runs before C1 serves or recovers anything. The migration also refuses a schema that is neither journal layout.
- **D8:**
  - Done: the context page is found by binary search (200 units at 64 KiB: 514 → 290 ms), and the visibility set is built once per pass.
  - Deferred: the context path adjacency; `context.select` takes about 23 ms.
  - Not measured: the keep-alive expiry change, which needs owner approval.
- **The reference phase, benchmark and sizing ran on a working tree with regenerated evidence files** (`working_tree_modified: true`). Product code was unmodified.
- **Flaky unit test fixed (test only):** `tests/unit/m03/test_tokens.py::test_time_claims_use_thirty_second_leeway_and_optional_nbf` failed twice under load. It computed its 31 s boundary tokens before starting its test server, so a few seconds' stall moved them inside the 30 s leeway. The rejected tokens now sit 35 s out, with `now` read just before signing.
- **Secret scan:** 105 digest false positives were baselined ([audit](../evidence/M14b/secret-audit.md)).

## Limitations

- The M14a read, `graph-context` and single-create targets are not met on makako, and the finalize gap there is unexplained.
- B3 still returns 503s on its first repeat.
- One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

Diagnose the makako finalize gap with per-call TerminusDB timing, about 15 minutes on the measurement host. The suspect is the 1-second keep-alive expiry, which would need owner approval to change. M15 is not started.
