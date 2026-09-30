# M09 — Coding-agent test-development context: execution report

**Gate:** VERIFIED

Approved plan: [M09](M09.md), revalidated against the M08 report (§1a) and authorized for implementation by the owner on 2026-09-29. Implementation revision: `@@REV@@`.

It was verified on the 441-input source listed in [`implementation-files.sha256`](../evidence/M09/implementation-files.sha256), whose file SHA-256 is `089ce8164e1421949a492f5caf0f7610b4e5c93df183ca56185c1244f74857bb`. The manifest matched both before and after the live gate. After the gate, one evidence file was audited as a secret-scan false positive ([audit](../evidence/M09/secret-audit.md)). The resulting [audited manifest](../evidence/M09/implementation-files-audited.sha256) differs only in `.secrets.baseline`, and the corrected `make check` passed. The committed implementation revision contains exactly the audited source.

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check | `make check`; [log](../evidence/M09/check.log), [exit](../evidence/M09/check-exit.txt) | PASS on the final source: 846 passed, 92 skipped, with Ruff, mypy, secrets (1,144 files), baseline and profile checks all passing. The makako copy passed `make check` before the last timeout edits ([log](../evidence/M09/makako-check.log)). |
| M09-T01–T06, plus the M01–M08 regression selection (92 cases), on makako.sf.nethserver.net (owner instruction) | `bash docs/evidence/M09/run-makako-gate.sh`; [precheck](../evidence/M09/makako-manifest-check-before-gate.log), [log](../evidence/M09/makako-live-integration.log), [JUnit](../evidence/M09/makako-live-junit.xml), [exit](../evidence/M09/makako-live-exit.txt), [host](../evidence/M09/makako-live-host-suspend.txt), [case check](../evidence/M09/makako-case-check.txt), [post-check](../evidence/M09/makako-manifest-check-after-gate.log) | PASS: 92 passed in 18,887.84 s (5:14:47). Exactly the 92 expected identities, with no failures, errors or skips. pytest, tee, restore and script all exited 0, and there was no suspend. The manifest was unchanged before and after. Settings: `C1_QUERY_TIME_BUDGET_MS=30000`, `C1_BACKEND_TIMEOUT_S=30`, `C1_FGA_DEADLINE=30s` (D13). M09 case times: T01 217.8 s (it includes nothing of the shared load, which ran in M08-T01), T02 37.5 s, T03 76.7 s, T04 38.9 s, T05 2,182.1 s, T06 3,958.9 s. |
| M01 probe (makako) | `bash docs/evidence/M09/makako-run-m01-probe.sh`; [log](../evidence/M09/makako-m01-probe.log), [JUnit](../evidence/M09/makako-m01-probe-junit.xml), [exit](../evidence/M09/makako-m01-probe-exit.txt) | PASS: 12 passed; all exits 0; committed M01 inventory restored unchanged |
| Consumer demonstration, no AI (A18), makako | `bash docs/evidence/M09/makako-run-demo.sh` (runs `run-demo.py` on a disposable repository); [env check](../evidence/M09/makako-demo-env-check.txt), [result](../evidence/M09/makako-demo-result.json), [full log](../evidence/M09/makako-demo.log), [exit](../evidence/M09/makako-demo-exit.txt) | PASS: demo 0; all six provider-key variables unset; external results a1 `fail`, a2 `pass` |
| Static no-AI scan | [scan](../evidence/M09/no-ai-config-scan.txt) | PASS. `pyproject.toml`, `deployment/compose.yaml` and `.env.example` contain no provider SDK or model setting. The new context modules import no network client. |

**Runtime and fixture.**
- **Runtime:** the gate ran on makako.sf.nethserver.net (4 vCPU, 7.6 GB RAM, no swap, Rocky Linux 9, Podman), using the same pinned images and a copy of the 441-input source verified by manifest. The development laptop ran `make check` and the unit tests. All six provider-key variables were unset for the gate, the consumer runner and the demo.
- **Fixture:** `software-integration` 1.1.0. It uses the same commits as M08, and its checked-in SCIP JSON is unchanged.
- **Consumer:** the external run uses the locked pytest in the project environment, runs in a temporary checkout, and has a minimal environment.

## Earlier gate attempts (not passes)

The failed attempts are kept as evidence, and none of them counts toward the gate.

| Attempt | Host and settings | Outcome | Cause and action |
|---|---|---|---|
| Laptop 1 (`attempt1-*`) | Laptop, 5,000 ms budget | 79 passed, then M08-T01 returned 503 `C1-SW-007` | Each authorized request costs about 3.5 s (the M05 per-resource binding re-verification); profile and latency evidence below. The owner approved a 10,000 ms default budget (D12). |
| Laptop 2 (`attempt2-*`) | Laptop, 10,000 ms | 80 passed, then M08-T02 `resolve` returned 503 after more than 10 s | This was a single stall. The isolated latency distribution is tight (3.3–3.85 s over 45 requests). |
| Laptop 3 (`attempt3-*`) | Laptop, 10,000 ms, host sampler | 79 passed, then the M08-T01 load failed with `httpx.RemoteProtocolError` | The sampler showed swap fully exhausted (4,095 of 4,095 MB), with browser and other desktop processes resident. The owner directed the gate to makako with longer delays (D13). |
| Makako 1 (`makako-attempt1-*`) | Makako, 30,000 ms / 30 s | 47 passed, then M03-T06 failed with "C1 API health deadline exceeded" | `scripts/api.py` used a fixed 30 s startup deadline with 15 s reads, which is below a 30 s backend timeout. Both now scale with `C1_BACKEND_TIMEOUT_S`, as do the fixed 10 s harness clients. Before the next full attempt, 29 targeted fault-injection tests passed on makako. |
| Makako 2 (`makako-attempt2-*`) | Makako, same settings | 7 passed, then M07-T07 failed with a transient `httpx.ReadError` (connection reset, no C1 frame) | It passed when rerun alone ([log](../evidence/M09/makako-attempt2-m07-t07-rerun.log)). This matches the M07 unexplained disconnects. |
| **Makako 3** | Makako, same settings | **92 passed** | This is the gate of record. |

Diagnostics:
- [First-request timing](../evidence/M09/first-request-diagnostic.json): optimizing the knowledge branch made no difference.
- [Lookup profile](../evidence/M09/lookup-profile.json): the time is in the planner's per-resource OpenFGA binding reads and checks.
- [Latency distribution](../evidence/M09/latency-distribution.json).

## Demonstration

This is a test-development package for `ledger.api.create_invoice`. The target is {a1, b1, `default`}, the goal is conformance, and the reader is Carol ([result](../evidence/M09/makako-demo-result.json), 39,665 rendered bytes). It contains:

- **Normative:** the five parts of `docs/invoicing.md` at a1, including "The amount must be greater than zero; zero is rejected with 422." It also contains the 1.0.0 `openapi.json` contract.
- **Implementation:** the complete a1 `create_invoice` unit, plus its complete direct dependencies: `Invoice` (models), `validate`, `InvalidAmount`, and `store.save`.
- **Tests:**
  - `ledger-create` is `definition-only`. Its runs are on a2 or under `py312`, and both are labelled `other-target`.
  - `shop-live` has a matching live a1+b1 run, labelled as integration evidence.
  - `shop-mocked` has a matching mocked b1 run, which is not integration evidence.
- **Instructions:** the `CONTRIBUTING.md` "Running tests" section, as untrusted text.
- **Discrepancy:** the imported review note, quoting both the rule and `return amount >= 0`.
- **Gaps:** the fixed dependency statement.

Next, the deterministic consumer ran. The reviewed test cites the documentation part and the contract part, and both are present in the package. The consumer checked out a1 and a2 and ran the test outside C1: it **failed on a1** and **passed on a2**. It imported the case and the two runs through `c1-svc-ci`. A repeated request then showed `consumer-zero-amount` as `matching-run: fail` at {a1, b1}, with the a2 pass labelled `other-target`.

Noninterference for restricted code is demonstrated by M09-T06. Dave's package for `submit_order` is byte-identical to the twin load's except for the revision, and it has no restricted path; Carol's package includes the restricted dependency.

## Deviations and refinements

[ADR-0018](../decisions/ADR-0018-software-task-contexts.md) and plan §1a record these.

- **D2, profile kind.** A software-task profile is a second, closed profile kind in the same catalog. The M07 graph model and its digests are unchanged. A new `catalog.get_any` returns either kind; `get` still returns a graph profile only.
- **D3, vocabulary.** The three predicates extend `software` to 1.1.0; there is no separate `software-testing` profile. The owner stated that there are no production installs and no migrations are needed, so development databases that hold 1.0.0 must be reinstalled. The `importMethod` enumeration also gains `review-notes`.
- **D6, run matching.** A run matches only when all of its snapshots are target snapshots and its configuration is a target configuration, or both are absent.
- **D7, dependency gap.** The dependency gap is a fixed statement on every package. It cannot be computed from hidden occurrences without leaking.
- **D9, fixture changes.** The fixture changes are data only:
  - The a1 defect was already present in M08.
  - The discrepancy is a checked-in review note, imported and attributed to the analyzer producer rather than authored by Carol.
  - Two runs were added: `mocked-b1` and `unit-a1-py312`.
- **M08-T02.** Its expected run set for {a1, b1} now also contains the two added runs. No other M08 assertion changed.
- **Shared harness.** The session-wide `software` load moved to `tests/integration/software.py` and is registered once in `tests/integration/conftest.py`. M08 and M09 therefore share one load per session. The M08 conftest re-exports the moved helpers.
- **D12, request budget (owner-approved 2026-09-30).** The default `C1_QUERY_TIME_BUDGET_MS` changes from 5,000 ms to 10,000 ms; the cap stays at 30,000 ms. This supersedes the M07 D22 default.
- **D13, configurable timeouts (owner instruction 2026-09-30).** Two new settings, both with unchanged defaults: `C1_BACKEND_TIMEOUT_S` (default 5 s, range 1–30 s) for the OpenFGA and OIDC clients, and `C1_FGA_DEADLINE` (default `3s`) for the OpenFGA server request and list-objects deadlines in `deployment/compose.yaml`. The API test launcher and the fixed-timeout harness clients now scale with these settings.
- **Markdown safety.** Stored text in labels and metadata is escaped by the M07 inline renderer; code and instructions are fenced. Tests compare escaped forms.

## Fixes made during implementation

- `prepare_units` evaluated `citation["evidence_id"]` eagerly as the default of `dict.get`. That broke units whose citations carry only an `id`, and it is now a conditional.
- The first live load failed validation (`C1-IX-030`) because `review-notes` was not an allowed `importMethod`. It was added to the profile.
- Four integration assertions were corrected:
  - Other-target runs legitimately name their own snapshots.
  - Matching status is looked up by test-case ID.
  - Markdown comparisons use the escaped forms.
  - 404 bodies are compared whole.

## Limitations and open items

- Only direct same-snapshot dependencies (depth 1) are expanded, and only through indexed reference occurrences. Cross-repository calls appear through interfaces, not through code expansion.
- The consumer demonstration checks that the reviewed test cites package evidence. It does not evaluate test-writing quality, and there is no LLM in the loop.
- **Request cost grows with readable resources.** Every authorized request re-verifies each readable resource's current binding and `can_read` in OpenFGA twice: once when building the plan and once when finalizing it (the M05 design). That is about 3.5 s per request for this fixture on the laptop. Request cost therefore grows linearly with the number of readable resources. Batching binding reads would change the verified M05 security path, so it needs its own plan.
- **Laptop gate reliability.** The laptop gate is unreliable when swap is exhausted. The gate of record ran on makako with 30 s budgets and timeouts. Its M09-T05 and T06 each take 36–66 minutes there.
- **Unexplained disconnects.** Transient connection resets still have no established cause (M07 and makako attempt 2).
- One agent both implemented and reviewed this milestone; there was no independent human review.
- `tests/unit/m03/test_tokens.py::test_time_claims_use_thirty_second_leeway_and_optional_nbf` failed once in a post-gate `make check`, then passed three isolated reruns and the final check. It computes `now` once, then checks a boundary 31 s away, so it can flake on a loaded host. The M03 test is unchanged.
- The M08 note on the owner-revertible GraphQL retry refinement (M07 D21) still stands.

## Next bounded action

No further planned milestone exists. Plan M10 (documentation-first support context) against this report. M10 is not authorized to start automatically.
