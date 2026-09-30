# ADR-0019 — Load-once fixture templates in the live test harness

**Status:** Accepted, 2026-09-30, on the owner's instruction ("do 1 + 3") after the M09 gate took 5 h 15 min on makako.
**Scope:** test harness and fixture producer only. No product behavior changes.

## Context

- **Where the gate time goes.** In the M09 gate, most of the time went to loading the `software-integration` fixture through the real producer path, not to the checks themselves. The gate loaded it five times: once for the shared session, twice in M08-T07 (real and twin), once in M09-T05, and twice in M09-T06.
- **Measured load cost.** One load is 26 ChangeSets and 585 records, and took 756 s on the laptop.
  - Each ChangeSet costs about 15–20 s, and more as the store grows. `scip/a1` took 28 s, but `scip/a2` took 40 s.
  - The `calls` runs, which carry cross-references, take about 50 s each.
  - The cause is the per-resource authorization verification (M05 design), recorded as a limitation in the M09 report.

## Decision

1. **Load once per session, copy per test.** `live_case(template)` can start from a `CaseTemplate` captured from a loaded case:
   - Both TerminusDB databases are cloned locally through `POST /api/clone`. A clone keeps the full commit history with the same commit IDs, so recorded revisions stay valid.
   - The template's OpenFGA tuples are written into a fresh store.
   - The instance ID is reused, because instance-level grants name it.

   Every copy is an independent repository with its own databases, store and lock. A session makes at most two loads through the real producer path: `software_template`, and `software_twin_template` (the load without restricted-scope records). The shared `software` case, M08-T07, M09-T05 and M09-T06 all use copies, so no test can alter a template.
2. **A smaller fixture.** The competing analyzer and the declared test context (execution instructions, fixture declarations) are ingested only for each repository's first snapshot (a1, b1). The a2/b2 runs repeated the same cases, and no test depends on them. The load is now 23 ChangeSets instead of 26. The CI report imports were not merged: one coverage record would then span several snapshots, which misrepresents coverage.

## What is and is not changed

- **What the tests exercise.** The tests still run against the real pinned TerminusDB, OpenFGA and Keycloak, with the same data, history and bindings. The ingestion path is still exercised: each template is built with the real producer and ChangeSet workflow, and M08-T04/T05 and M09-T05 still write through it.
- **What a copy skips.** A copy skips only the repeated ingestion. It does not skip any authorization, validation or rendering step under test.
- **Correctness of the copy.** A harness probe confirmed that copied knowledge and journal heads, commit history and tuples are identical to the template's, that the copy is readable, and that it is independent. The live M08+M09 run and the full regression are recorded in `docs/evidence/ADR-0019/`.

## Measured effect (laptop)

- **M08 and M09 tests:** 13 passed in 35 min. Before, they took about 1.5 h on the laptop, and M09-T05/T06 alone took 1.7 h on makako. The two template loads take about 12.5 min each; the tests themselves take 9–125 s each.
- **Decision 2 (smaller fixture):** the effect is within noise, 753 s compared with 756 s per load. Removing three small ChangeSets saves little, because the per-ChangeSet cost is dominated by work that grows with store size.
- **The remaining lever** is batching the authorization binding reads (option 5 in the discussion), which needs its own plan.

## Verification

| Check | Evidence | Result |
|---|---|---|
| `make check` | [log](../evidence/ADR-0019/check.log), [exit](../evidence/ADR-0019/check-exit.txt) | PASS: 846 passed, 92 skipped |
| M08 and M09 on the laptop | [log](../evidence/ADR-0019/laptop-m08-m09-copies.log) | PASS: 13 passed in 2,113 s |
| Full 92-case regression on makako (same selection and M09 D13 settings as the M09 gate of record) | `bash docs/evidence/ADR-0019/run-makako-gate.sh`; [precheck](../evidence/ADR-0019/makako-manifest-check-before-gate.log), [log](../evidence/ADR-0019/makako-live-integration.log), [JUnit](../evidence/ADR-0019/makako-live-junit.xml), [exit](../evidence/ADR-0019/makako-live-exit.txt), [case check](../evidence/ADR-0019/makako-case-check.txt), [post-check](../evidence/ADR-0019/makako-manifest-check-after-gate.log) | PASS: exactly the 92 expected cases passed in 10,456 s (2:54:16), with every exit 0 and no suspend. Before, the run took 18,888 s (5:14:47). The M08 and M09 cases took 4,936 s, down from 13,367 s. |

The 441-input source is recorded in [`implementation-files.sha256`](../evidence/ADR-0019/implementation-files.sha256), and it was unchanged before and after the makako run.

## Rejected alternatives

- **Seeding test databases directly, bypassing ChangeSets.** Rejected: it creates a second writer that would have to stay equivalent to the real path.
- **Merging CI imports into one run.** Rejected: coverage records are per snapshot.
