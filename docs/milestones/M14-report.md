# M14 — Retrieval and storage benchmark: execution report

**Gate:** VERIFIED

Approved plan: [M14](M14.md) (§1a revalidated against the M13 report on 2026-10-05). The owner authorized the work on 2026-10-04 ("Implement M13, Plan M14, implement and run M14") and the makako run on 2026-10-05.

Gate evidence: makako run **attempt 2** at revision `8048049`. The owner chose to rerun attempt 2 at the then-current HEAD. That revision already contains the first M14a content-path changes (commit-keyed content cache, batched record reads, the context budget early exit). It does **not** contain M14a's authorization-path changes. Its numbers are therefore the "before" baseline for those, and the M14a report compares against them. Host: makako (4 vCPU DO-Regular, 7.5 GiB, Rocky Linux 9.8, rootful Podman 5.8.2). Image `9571ffd07ce0…` built from `8048049` ([image](../evidence/M14/image.txt)).

## Named checks

| Check | Evidence | Result |
|---|---|---|
| M14-T01–T06 at S and M | `bash docs/evidence/M14/run-benchmark.sh`: [log](../evidence/M14/integration.log), [JUnit](../evidence/M14/junit.xml), [exit](../evidence/M14/exit.txt), [run log](../evidence/M14/run.log), results [S](../evidence/M14/results-S.json) / [M](../evidence/M14/results-M.json) | PASS: 6 passed in 22,362 s (6:12:42), pytest exit 0 |
| Corpus and gold | [manifest S](../evidence/M14/corpus-manifest-S.json), [manifest M](../evidence/M14/corpus-manifest-M.json), gold [S](../evidence/M14/gold-S.json) / [M](../evidence/M14/gold-M.json) | The digests in both results equal the committed manifests. S: 932 records (854 readable by the tested principal), 53 needs. M: 2,792 records (2,558 readable), 57 needs. |
| Baseline and compare | [`benchmark/baselines/v1-makako.json`](../../benchmark/baselines/v1-makako.json), [compare against itself](../evidence/M14/compare-self.json) | Written by `python -m benchmark baseline`. Compare: no hard failures, no changes, no performance warnings at S or M. |
| Unit checks | `tests/unit/m14` (corpus determinism, gold independence, metrics, compare, canonicalization, configurations, twin) | PASS in `make check` |

## Results (makako, attempt 2)

**T01 storage fidelity: 1.0 at both scales.** Every record round-trips field by field. Every declared conflict keeps both claims, document parts keep their order and text digests, and the export round trip gives identical identities.

**T02 retrieval quality** (macro over needs; C1's own order, nothing re-ranked):

| Family / strategy | S: Recall@10 / @50 | S: nDCG@10, MRR | M: Recall@10 / @50 |
|---|---|---|---|
| keyword (exact) | 0.867 / 1.0 | 1.0, 1.0 | 0.807 / 0.949 (two needs have 72 and 84 relevant items) |
| alias, document, valid-at (exact) | 1.0 / 1.0 | 1.0, 1.0 | 1.0 / 1.0 (valid-at @10: 0.99) |
| label prefix (exact) | 1.0 / 1.0 | 1.0, 1.0 | 0.979 / 1.0 |
| graph: keyword-only | 0.0 / 0.0 (battery recall 0.571) | 0, 0 | 0.0 / 0.0 |
| graph: neighborhood, type-filtered | 0.476 / 1.0 | 1.0, 1.0 | 0.476 / 1.0 |
| graph: `graph-context` | 0.476 / 1.0, path recall 1.0 | 1.0, 1.0 | 0.476 / 1.0, path recall 1.0 |
| context (8 / 32 / 64 KiB) | coverage: 64 KiB reaches 1.0 over 3 pages; 8 and 32 KiB refused (422, minimum 57,440 bytes) | — | same |

- **Exact semantics hold.** There are no exact-semantics failures: keyword, alias, valid-at and document results equal the gold sets.
- **Why some recall@10 values are below 1.** Recall@10 is below 1 only where a need has more than 10 relevant items.
- **What the graph rows show.** Keyword-only retrieval cannot find versions that lack the anchor's keyword (the A15 pattern). The typed traversal and `graph-context` find all of them.

**T03 security invariance: 1.0** (122 of 122 observations at S, 130 of 130 at M). Adding highly relevant hidden resources (98 at S, 104 at M), then modifying them, changed no visible result, count, order, path, explanation or context byte.

**T04 revocation: passed.** After revoking the team reader role, no team resource appeared at head or at the pre-revocation revision. After the role was granted again, every observation equals the baseline.

**T05 performance** (medians of 5 repeats; makako; this host only):

| | S | M |
|---|---|---|
| Corpus load | 436 s | 1,372 s |
| TerminusDB storage | 0.44 MB → 11.9 MB | 0.44 MB → 34.8 MB |
| Simple read (keyword, alias, label, valid-at, document, neighborhood) | 3.2 s, 57 OpenFGA requests | 6.5–6.8 s, 163 OpenFGA requests |
| `graph-context` 64 KiB | 9.7 s | 21.1 s |
| Refused context (8/32 KiB) | 2.1 s | 3.8–4.0 s |
| Hidden twin add (98 creates) / modify (36 replaces) | 97 s / 244 s | 111 s / 274 s |
| C1 memory peak | 155 MiB | 291 MiB |

**T06 configurations.** `deterministic` ran. `semantic-seeds`, `semantic-plus-gate` and `hybrid-plus-gate-plus-graph` are `NOT_AVAILABLE` (M15, M16 and M18 are not implemented). The baseline needs no optional component.

## Attempt 1 (not gate evidence)

[`attempt1-*`](../evidence/M14/attempt1-run.log) ran at `d15b118`, the M13 product revision, in 9:43:53. T01, T03, T04 and T06 passed, with fidelity, security and revocation at 1.0 at both scales. Two harness defects failed it:
- **T02** demanded recall@50 = 1.0 for keyword needs with 72 and 84 relevant items, although C1 returned exactly the gold set.
- **T05** could not measure storage under rootful Podman.

Both were fixed in `8048049`. Attempt 1's makako read medians (about 8 s per simple read at S, 23.5 s for 64 KiB contexts) are the pre-M14a figures.

## Deviations and refinements

- **Corpus record shapes** follow the loaded profiles: document order keys `p1…p6` (keys may not end in `0`), year bounds with and without a timezone.
- **Valid-time gold follows ADR-0007.** A bound without a timezone is indeterminate and matches only with `include_unknown`.
- **The export round trip covers the `/v1/export` scope** (entities, assertions, sources, evidence). Documents are checked through the parts API.
- **Proxy timeouts during benchmark writes** are reconciled by reading the ChangeSet, never by applying twice. In attempt 2, the 36-replace modification completed in 244–274 s, under the 300 s proxy timeout.
- **Development-only switches** (`C1_BENCH_REUSE`, `C1_BENCH_SKIP`) exist for harness work. The gate run set neither.
- **The plan's D4 asked for about 60 needs per scale.** The corpus has 53 (S) and 57 (M); the families and strategies are as planned.
- **Defects found by the benchmark** and fixed during M13 (ADR-0024): the self-blocking document and part apply, and the history and historical-read scale problems.

## Limitations and open items

- These are performance measurements on makako only, not scalability claims. Per-request cost still grows with readable resources (OpenFGA requests 57 → 163 from S to M). M14a addresses this.
- C1's result order is deterministic, not relevance-ranked. The quality numbers record that as it is.
- One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

M14a (performance hardening; owner-approved insertion before M15) is implemented, and its makako gate is running. Its report compares against this baseline with `python -m benchmark compare`.
