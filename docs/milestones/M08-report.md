# M08 — Software profile and source-version ingestion: execution report

**Gate:** VERIFIED

Approved plan [M08](M08.md), plan commit `910d3ec`. Implementation revision: `5b598ca7e0e46bfe1ce0b1200b18557346265d8b` (the commit containing exactly the verified source). It was verified on the 421-input source listed in [`implementation-files.sha256`](../evidence/M08/implementation-files.sha256), file SHA-256 `d835525d43e00b5bb2fac867875a7673b913b21a4d08a27633402be70cfe0446`. That manifest matched before and after the live gate. The same source is committed as the implementation revision.

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check | `make check`; [log](../evidence/M08/check.log), [exit](../evidence/M08/check-exit.txt), [secret audit](../evidence/M08/secret-audit.md) | PASS: 827 passed, 86 skipped; Ruff, mypy (267 files), secrets (1,047 files), baseline, core and software profile checks passed |
| M08-T01–T07 and the M01–M07 regression selection (86 cases) | `bash docs/evidence/M08/run-regression-gate.sh`; [precheck](../evidence/M08/manifest-check-before-gate.log), [log](../evidence/M08/regression-live-integration.log), [JUnit](../evidence/M08/regression-live-junit.xml), [exit](../evidence/M08/regression-live-exit.txt), [host](../evidence/M08/regression-live-host-suspend.txt), [case check](../evidence/M08/regression-case-check.txt), [post-check](../evidence/M08/manifest-check-after-gate.log) | PASS: 86 passed in 5,133.32 s (1:25:33); exactly the 86 expected identities, no failures, errors or skips; pytest/tee/restore/script exit 0; no host suspend; manifest unchanged before and after |
| M01 probe | `bash docs/evidence/M08/run-m01-probe.sh`; [log](../evidence/M08/m01-probe.log), [exit](../evidence/M08/m01-probe-exit.txt) | PASS: 12 passed; committed M01 inventory unchanged; all exits 0 |
| Producer CLI and demonstration, no AI | `bash docs/evidence/M08/run-demo.sh`; [env check](../evidence/M08/demo-env-check.txt), [producer](../evidence/M08/demo-producer.log), [demo](../evidence/M08/demo.log), [exit](../evidence/M08/demo-exit.txt) | PASS on the second attempt: producer 0 (idempotent rerun on the loaded development instance), demo 0, all six provider-key variables unset. The first attempt's demo failed closed with 503 `C1-SW-007` (`time_budget`, default 5,000 ms) on its first request immediately after the long gate, while the producer succeeded; see [attempt 1](../evidence/M08/attempt1-demo.log). No code changed between attempts |
| Static no-AI and SCIP-tool scan | [scan](../evidence/M08/no-ai-config-scan.txt) | PASS: no provider SDK or model setting in `pyproject.toml`, `deployment/compose.yaml`, `.env.example`; no SCIP tool in `pyproject.toml` or `uv.lock` |

Runtime: CPython 3.13 (uv 0.12.2), the pinned compose stack (TerminusDB, OpenFGA, Keycloak, PostgreSQL) with its M07 images, all six provider-key variables unset in the gate and demo. Fixture: `software-integration` 1.0.0 (commits a1 `4c4c16d1…`, a2 `66f589fc…`, b1 `eecb5405…`, b2 `8778ea5e…`), SCIP generated once by scip-python 0.6.6 and scip CLI v0.10.0 ([provenance](../../fixtures/software-integration/scip/PROVENANCE.json)).

## Demonstration (A21, A22 source protection)

`scripts/demo_m08.py` ([output](../evidence/M08/demo.log)) prints:
- the resolved target {ledger a1 `4c4c16d1…`, shop b1 `eecb5405…`};
- the pinned definitions of `ledger.api.create_invoice` (`ledger/api.py` line 15) and `shop.client.submit_order` (`shop/client.py` line 12), each a complete code unit at its commit;
- each relationship with its basis and origin: declared, structural, static-extraction, interpretive (derived), and observed;
- b1 coverage. Carol sees four records, including the `scip-occurrences` record for `sw-restricted` that covers `shop/pricing_internal.py`. Dave sees three records, with no restricted path or record.

M08-T07 shows the same results for Dave are identical to a twin load that never contained the restricted module.

## Deviations from the plan

Each deviation is recorded in [ADR-0017](../decisions/ADR-0017-software-profile.md).

- **D7, logical InterfaceOperation.** The operation is keyed by provider and `operationId`, and each contract version is linked by `specifiedIn`. A versioned operation would have made a client's declared `operationId` name every contract version, asserting compatibility that was never observed. The target's contract member selects the version.
- **Conflict 3, class-checked references (now enforced at write time).** The plan deferred write-time class checks. SHACL `sh:class` could not validate references outside the batch, so the implementation added `C1-CS-013`: any field whose ranges are all registered classes must reference a readable record of one of those classes. A record with an unreadable required class-ranged reference is hidden on reads and queries. This changes behavior for existing profiles only where a reference already had the wrong class.
- **D10, coverage digest per scope.** A whole-run digest would depend on hidden records, so each coverage record digests only its own scope's records.
- **D11, idempotency key.** The key covers the batch content and base revision, and a per-batch existence probe resumes an interrupted run. The planned key over the run payload could not distinguish a changed retry from an exact one.
- **M07 D21 refinement, flagged for the owner.** The single disconnect retry now also covers read-only GraphQL POST queries, because the batched fetch uses them and one was dropped during a load. Mutations and other POSTs are still never retried. The owner may revert this.
- **Expected outputs.** Expected values are asserted in the T-tests from the independently specified `fixture.json`. There is no separate `expected/` directory.
- **M08-T07 design.** T07 writes (a hidden snapshot and a rescope of b1 `shop/client.py`) and compares a twin load, so it uses its own two fresh repositories instead of the shared session load.

## Fixes made during implementation

- Order-independent profile digests: the registry keeps an identical redeclaration of another extension's predicate.
- Profile install recovery no longer duplicates the profile's classes, and it compares decoded markers.
- Batched fetches replace per-ID class probes, which took about 1.7 s per ID.
- `_DecisionMemo` deduplicates authorization per request step and fails closed if the security journal head moves. Before this, applying 78 records took 631 s; now it takes about 46 s.
- The journal listing is reused only at the identical backend data version.
- Documentation applicability is declared per copy.
- Planner runs are repeatable.
- Tests fetch fresh tokens for long loads.

## Limitations and open items

- The same-name profile upgrade defect remains. M09 extends `software` in place only because the owner confirmed that there are no production installs.
- AsyncAPI and non-Python languages are deferred. The SCIP subset excludes local symbols, parameters and module terms, and counts them as out of scope.
- A single fixture load takes about 12 minutes on the development laptop, which is why T07 takes about 25 minutes. That time is dominated by ChangeSet validation and apply over the real stack.
- One agent implemented and reviewed this milestone; there was no independent human review.
- On a development instance that holds all earlier fixtures, the first software request after a long idle or gate period can exceed the default 5,000 ms budget; it fails closed (503). The budget is configurable to 30,000 ms (M07 D22).

## Next bounded action

Implement M09 from its revalidated plan (authorized by the owner on 2026-09-29).
