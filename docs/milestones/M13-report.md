# M13 — Release hardening and operational acceptance: execution report

**Gate:** VERIFIED

Approved plan: [M13](M13.md), plan revision `ec4a6d0`. On 2026-10-04 the owner authorized implementation ("Proceed as you suggest. Implement M13, Plan M14, implement and run M14"), which adopted the plan's recommendations for all five open decisions:
- **OD1:** an nginx TLS proxy.
- **OD2:** quiesced backups.
- **OD3:** version `0.1.0rc1` with a local annotated tag only. The tag was later pushed by accident; the owner kept it published (see Limitations).
- **OD4:** makako as the measurement host.
- **OD5:** the development stack is stopped during reference phases.

Implementation revision: `6a0ca7c`. It ran the reference-deployment phase (T01, T03–T08). The T02 regression gate ran on `d15b118`, which differs from `6a0ca7c` only in `benchmark/runner.py` (M14 code; the gate does not import it). All live evidence is from makako.sf.nethserver.net:
- Rocky Linux 9.8, kernel 5.14.0-687;
- 4 vCPU "DO-Regular", 7.5 GiB, no swap;
- rootful Podman 5.8.2, SELinux enforcing.

The candidate image is `localhost/c1:0.1.0rc1`, image ID `9bc25b6b961c…` (built from `6a0ca7c` by the phase script: [image record](../evidence/M13/reference-image.txt)). It is built locally and was not pushed.

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check | `make check` on the laptop, and on makako at `d15b118` before the gate | PASS: 930 passed, 133 skipped (live cases). Ruff, format, mypy (382 files), secrets (1,599 files), baseline, OpenAPI parity and license inventory all passed. |
| M13-T01 Clean no-AI deployment | `tests/integration/m13/test_t01_clean.py` (3 cases) | PASS. Clean bootstrap; only the proxy port is published, and egress from the C1 container is unreachable. Create, review, query, history and export work, as do document views for alice, bob and carol, the M07 golden context and every context profile. Browser flows over TLS pass with a CSP on every HTML page. |
| M13-T02 Full regression | `bash docs/evidence/M13/run-makako-gate.sh`. Evidence: [log](../evidence/M13/makako-live-integration.log), [JUnit](../evidence/M13/makako-live-junit.xml), [exit](../evidence/M13/makako-live-exit.txt), [host](../evidence/M13/makako-live-host-suspend.txt), [case check](../evidence/M13/makako-case-check.txt), [expected cases](../evidence/M13/regression-expected-cases.json) | PASS on attempt 1: 119 passed in 16,333 s (4:32:12). pytest, tee, restore and script exited 0. Case check: 119 expected, 119 executed, none missing, extra or not passed. No host suspension. |
| Acceptance matrix A01–A22, G1–G9 | `scripts/acceptance_matrix.py --junit makako-live-junit.xml --junit reference-junit.xml`; [matrix](M13-acceptance.md), [check](../evidence/M13/acceptance-check.json) | PASS: 22 scenarios, 9 gates, 85 mapped checks, 0 problems. Every mapped check executed once and passed, and the G1 evidence files exist. |
| M13-T03 Knowledge-only restore | `test_t03_knowledge_restore.py` | PASS. After a quiesced backup, the Company A note is re-scoped and a part is narrowed; then the knowledge is restored. Current bindings still govern: the note is gone for alice in reads, history and export, and the team part is gone for bob. The post-backup entity is absent. A draft based on the pre-restore head is refused at apply (409 `stale_base`). A new ChangeSet applies. A backup that predates a later profile installation is refused before any change. |
| M13-T04 Full disaster recovery | `test_t04_disaster_recovery.py` | PASS. The full backup is restored into an isolated project `c1-dr`. It answers 503 until `dr verify` passes. An injected tuple mismatch makes `dr verify` fail, and `dr release` refuses without a passing verify. After release, the revoked grant and the re-scoped part are still enforced. |
| M13-T05 Failure/race matrix | `test_t05_failures.py` plus the T02 checks; [matrix](../evidence/M13/failure-matrix.md), [observed](../evidence/M13/t05-reference-faults.json) | PASS. Observed outcomes:<br>• OpenFGA paused: readiness 503 and a read returns no content (404).<br>• Keycloak stopped: unready; an issued token still validates from the JWKS cache (200).<br>• TerminusDB stopped: 503.<br>• C1 killed during apply: the first response is 502; after the restart the ChangeSet is still approved, and the retry with the same key gives 200 and exactly one receipt.<br>• Consistency check after the faults: true.<br>Every §15.4 row maps to executed checks. |
| M13-T06 API and portability | `tests/unit/m13` (OpenAPI parity, wheel contents) and `test_t06_portability.py` | PASS. `docs/api/openapi.json` equals the implemented routes (48 paths). The export is parsed by rdflib and imported by `import_jsonld` with identical identities. A remote context and an incompatible profile change are refused. Schema installation is repeatable. |
| M13-T07 Measured bounds | `scripts/bench_m13.py` on `c1-ref`; [bench.json](../evidence/M13/bench.json), [log](../evidence/M13/bench.log), [limits](../operations/limits.md) | PASS against the roadmap contract: every listed quantity was measured with the host record before and after, and the failure behavior is published. Two plan-level deviations are recorded below: the dataset sizes, and the candidate limit being preempted by the time budget. |
| M13-T08 Packaging and security audit | `test_t08_audit.py`, which runs `scripts/release_audit.py` and `license_inventory.py --check`; [audit](../evidence/M13/release-audit.json), [inventory](../release/third-party.json), [notices](../../THIRD_PARTY_NOTICES) | PASS: 0 findings. The image has no `.env`, keys, fixtures, AI SDK or plugin loader, and its entrypoint drops to UID 10001. Only the proxy publishes a port. 30 Python distributions and 7 images are inventoried with license files, 0 problems. |

**Reference phase.** `bash docs/evidence/M13/run-reference-phase.sh` ran on attempt 3 ([log](../evidence/M13/reference-integration.log), [JUnit](../evidence/M13/reference-junit.xml), [exit](../evidence/M13/reference-exit.txt)): 8 passed in 5,567 s (pytest exit 0), then the bench (exit 0), from 05:57 to 10:09 UTC. Per case:

| Case | Seconds |
|---|---|
| T01 isolation, no AI, ports (includes the session fixture load) | 3,455 |
| T01 API workflows, documents, every context profile | 397 |
| T01 browser flows over TLS | 248 |
| T03 knowledge-only restore | 549 |
| T04 guarded disaster recovery | 321 |
| T05 service faults | 337 |
| T06 export and schema | 32 |
| T08 audit and inventory | 226 |

Earlier attempts are not gate evidence and are kept as `reference-attempt{1,2}-*`:
- **Attempt 1:** SELinux denied the containers reading the compose file secrets (PostgreSQL "Permission denied"). The laptop has no SELinux. `c1-admin` now labels the generated files.
- **Attempt 2:** T01's golden context had identical normalized content, but its `rendered_bytes` was 29,519 against the golden's 29,739. That count includes this deployment's escaped principal IDs (44 occurrences, 5 bytes shorter each), which the comparison substitutes. T01 now masks only that line and asserts that the count equals the exact UTF-8 length.

## Measured bounds on makako (T07)

These are facts for this host only. The full tables are in [limits.md](../operations/limits.md).

- **Reads.** A 50-item entity list over 300 entities and 600 assertions (one readable scope) takes 16.8 s (median of 5). At 1,000 and 1,500 entities, every read exceeded the 30 s query budget and returned 503 `C1-QY-053` with no partial page. OpenFGA requests per list: 85 at 300 entities, 106 at 1,000, 121 at 1,500. C1's memory peak was 204–383 MiB.
- **Context and documents (loaded fixtures).** `graph-context` 13.8 s (75 KB), `documentation-update` 13.4 s (143 KB), document render 13.4 s.
- **Writes.** ChangeSet apply takes 32 s for 1 operation, 53 s for 50 and 126 s for 200; validate takes 4.8–19 s. With 2 or 4 concurrent writers on one base, exactly one applies and the others are refused as stale (409).
- **Limits.** A body over 1 MiB gives 413. A context budget below one unit gives 422 `C1-CX-010` (minimum 16,842 bytes). 5,490 readable resources give 503 `C1-QY-053`.
- **Backup and restore.** A quiesced knowledge-only backup takes 97 s (75 MiB); the restore takes 115 s.

## Deviations and refinements

Design choices are recorded in [ADR-0024](../decisions/ADR-0024-deployment-backup-recovery.md).

- **Product defects found by the reference runs and fixed** (unit tests added; the T02 regression passed with them):
  - `/v1/history` exceeded the 30 s backend timeout: every storage class was probed with a TerminusDB history call whose cost grows with the commits and the data. It now probes only the storage IDs that exist at head, because instance documents are never deleted.
  - Context and queries at a revision older than a later profile installation sent every ID of every newer class through per-document reads (4,104 reads for one request). TerminusDB's exact "unknown class" GraphQL error now means "no documents of that class at that commit".
  - A ChangeSet that replaced a document and one of its parts blocked itself. The reconciliation recheck of the part's document did not exclude the apply's own pending operation, so C1 stayed unready. Found by the M14 benchmark.
- **SELinux labeling** (`c1-admin` runs `chcon -t container_file_t` on its generated bind-mount files when SELinux is enabled). The plan did not anticipate rootful Podman with SELinux.
- **W1: bundles are not backups.** `terminusdb bundle` output fails to unbundle on a fresh server (`unknown_layer_reference`). Backups therefore export the storage volume, and knowledge-only restore clones from a temporary restore server (ADR-0024).
- **D12 / T05:** the plan expected protected reads to answer 503 while OpenFGA is paused. The verified M03-T06 behavior is a non-disclosing 404 with readiness 503. The check asserts fail-closed with no content and accepts either status ([matrix](../evidence/M13/failure-matrix.md)).
- **T03:** the plan expected the pre-restore draft to be refused at submit. C1 checks the base at apply (M04 semantics), so the draft may validate and be approved, but apply refuses it with 409 `stale_base`.
- **D11 dataset sizes:** the plan named B1 500/1,500, B2 2,000/6,000 and B3 4,500 readable resources. The bench uses 300, 1,000 and 1,500 entities with two assertions each (900, 3,000 and 4,500 readable resources), so that B3 stays under the 5,000-candidate limit. Over-limit behavior is measured separately at 5,490.
- **D11 candidate limit:** the plan expected 5,001 candidates to give 422 `C1-QY-052`. On makako the provisional candidate snapshot already exhausts the 30 s time budget, so the response is 503 `C1-QY-053`, which is also a documented, fail-closed limit. The 422 path is covered by `tests/unit/m05/test_plan.py`, and the laptop run returned it. limits.md states what makako did.
- **D11 OpenFGA counts** are counted from the OpenFGA request log, not through the client in the bench process. The bench calls C1 over HTTPS and has no FGA client.
- **T01 golden:** only the self-referential byte count is masked (see attempt 2).
- **Harness:** token grants are serialized per identity, because concurrent password grants tripped Keycloak's brute-force check, and generated test passwords never start with `-`.

## Limitations and open items

- **Performance on the measurement host is low.** Per-request cost grows with the number of readable resources: candidate content is read in per-class chunks, and each candidate is checked against OpenFGA. On makako, list reads over about 3,000 readable resources exceed the 30 s budget. ChangeSet apply is tens of seconds. `get_record` probes every declared class one after another. Replace-heavy ChangeSets that reference other scopes take minutes (M14 measured 9 minutes for 36 replaces on the laptop) and can outlast the proxy's 300 s timeout, although the apply completes. None of this was optimized in M13; these are candidates for an owner-planned performance milestone.
- **History cost** still grows with commits and data (about 5 s per TerminusDB history probe at 850 documents). The workflow journal accumulates commits, and TerminusDB `optimize` is not scheduled.
- **Backups are quiesced:** C1 serves nothing for about 1.5 minutes per backup on makako. There is no online backup.
- **Deployment specifics:** the reference host names (`c1.test`, `auth.c1.test`, port 18443) are hard-coded. Docker Compose is untested.
- **Release identity:** version `0.1.0rc1`, annotated tag `v0.1.0rc1` on `6a0ca7c`. The tag was meant to stay local (OD3). The repository's `push.followTags=true` pushed it to GitHub with the report commit on 2026-10-05, and the owner then decided to keep it published. No image was published.
- **Review:** one agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

M14, the benchmark, was planned with this milestone and is already running on makako at the owner's request; its report follows separately. Optional extensions M15–M18 are not planned. No other milestone starts automatically.
