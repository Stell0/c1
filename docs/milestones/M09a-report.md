# M09a — Batched current-authorization verification: execution report

**Gate:** VERIFIED

Approved plan: [M09a](M09a.md), plan commit `cc5f940`. Implementation authorized by the owner on 2026-10-01 ("proceed"). Implementation revision: `c00b952`. Its parent `0b9b944` changes only README.md, which is outside the manifest.

The milestone was verified on the 450-input source in [`implementation-files.sha256`](../evidence/M09a/implementation-files.sha256). That file's own SHA-256 is `f7f167fccea428386fabf14766a74f5a76f3a88b65f5be9763012fa529c55c76`. The manifest matched before and after the gate. All runs were on makako.sf.nethserver.net, because the development laptop was short of memory and the owner instructed "test on makako".

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check, run on makako | `make check`; [log](../evidence/M09a/check.log), [exit](../evidence/M09a/check-exit.txt) | PASS: 858 passed, 98 skipped. Ruff, format (450 files), mypy (292 files), secrets (1,273 files), baseline and profile checks all passed. |
| M09a-T01–T05 plus the M01–M09 regression selection (98 cases) | `bash docs/evidence/M09a/run-makako-gate.sh`. Evidence: [precheck](../evidence/M09a/makako-manifest-check-before-gate.log), [log](../evidence/M09a/makako-live-integration.log), [JUnit](../evidence/M09a/makako-live-junit.xml), [exit](../evidence/M09a/makako-live-exit.txt), [case check](../evidence/M09a/makako-case-check.txt), [post-check](../evidence/M09a/makako-manifest-check-after-gate.log) | PASS (attempt 8): 98 passed in 11,406 s, exit 0. Case check: 98 expected, 98 executed, 0 missing, extra or not passed. Post-gate manifest PASS. No network events during the run. |
| Same-host before/after measurement | `docs/evidence/M09a/measure-load.py`, run on the pre-M09a commit `2d1502e` and on this source; [before](../evidence/M09a/measure-before.json), [after](../evidence/M09a/measure-after.json) | See below. |

**Settings:** M09 D13 timeouts (budget 30,000 ms, backend 30 s, OpenFGA deadline 30 s). All provider-key variables were unset.

### Per-check results (attempt 8)

| Check | Cases | Result |
|---|---|---|
| M09a-T01 decision equivalence (scan and per-resource) | 2 | PASS |
| M09a-T02 no cached authority | 1 | PASS |
| M09a-T03 scan failure is closed (page cap, OpenFGA pause) | 1 | PASS |
| M09a-T04 bounded work | 1 | PASS |
| M09a-T05 profile changes still detected | 1 | PASS |
| M09a-T06 full regression, M01–M09 selection | 92 (M01 12, M02 9, M03 18, M04 14, M05 12, M06 7, M07 7, M08 7, M09 6) | PASS |

## Measured effect (makako, same host and settings)

| Measure | Before (`2d1502e`) | After | Change |
|---|---|---|---|
| One `software-integration` load (23 ChangeSets) | 1,528.6 s | 1,297.3 s | −15% |
| One software lookup (Carol, {a1, b1}) | 11.0–11.5 s | 8.2–9.6 s | about −28% |
| OpenFGA `read` calls per lookup | 1,224 | 14 | −99% |
| OpenFGA BatchCheck calls per lookup | 26 | 26 | unchanged |
| OpenFGA calls in one load | 5,030 | 5,030 | unchanged |
| Profiled `calls/a2` ChangeSet (laptop, `baseline-profile.json`) | 42% of time in whole-journal copies, 14% in catalog re-parsing | Removed by D1 and D5 | — |

The binding batching works as designed: one lookup now makes 14 reads instead of 1,224. The wall-clock gain is smaller than the read reduction, for two reasons:
- **Lookup time:** most of the remaining time is outside the binding reads, in record fetch, selection and rendering. It has not been profiled yet.
- **ChangeSet path:** ChangeSet review and apply still decide one resource at a time through `_DecisionMemo`. That step-level batching was planned (D3) but not wired. Each single decision is now cheaper, through the view and cached parsing, but the OpenFGA call count per load is unchanged.

## Deviations and refinements

These are recorded in [ADR-0020](../decisions/ADR-0020-batched-current-authorization.md).
- **D2:** the hot paths read immutable security views and never list or copy the journal. Administrative `Journal.list` callers keep copies.
- **D3:** `_DecisionMemo` was **not** changed to pre-fetch a step's IDs in one `check_many`. Its single decisions use the new view-based path. This is the main remaining cost in loads, and it is open below.
- **D4:** the scan rule compares sequential round trips, `ceil(bindings × 1.1 / 100) + 1 < ceil(n / 16)`. The planned rule compared request counts, and would have scanned for three IDs.
- **D5:** `load_candidate` returns deep copies. A unit test showed that callers extend returned registries, so a shared cached registry would be corrupted. Readiness detection uses the shared parses read-only.
- **D7:** the T04 ceilings were implemented as follows:
  - **Lookup:** at most two exact binding passes, so at most 2 × (pages + 1) reads.
  - **ChangeSet:** at most 40 journal listings and fewer than 200 OpenFGA checks for one 20-record ChangeSet. Before M09a a comparable ChangeSet copied the journal more than 1,000 times.
  - **Readiness:** no catalog re-parse.
- **Planner seam.** The binding count reaches `_authorize` through a request-scoped context variable, which keeps the existing `_authorize` test seams. Plane-test fake journals gained `view()`.

## Gate attempts on makako

Attempts 1–7 are kept under `docs/evidence/M09a/makako-attempt<N>-*`. No attempt failed an assertion; each stopped on an infrastructure error.

| Attempt | Outcome | Action |
|---|---|---|
| 1–3 | Podman DNS failures (`no route to host`); OpenFGA lost Postgres | Stack recreated; network watchdog added; **owner:** pin the Postgres address |
| 4 | 85 of 98 passed; M08-T07 setup hit `httpx.ReadError` while NethServer deployed another module on the host | **Owner:** full rerun |
| 5 | 97 of 98 passed; M09a-T04 hit `httpx.ReadError`. A diagnostic rerun of T04 and T05 passed twice | Gate tracebacks changed from `--tb=line` to `--tb=short` |
| 6 | Case 10 (M06-T02) hit `ReadError` in `Terminus._request` on a read-only GraphQL chunk | The owner declined to extend the M07 D21 retry and chose a short keep-alive expiry for `c1.storage.terminus` |
| 7 | Case 23 (M01-T06 `binding`) got `RemoteProtocolError` in the M01 probe's TerminusDB client | The same keep-alive expiry was applied to `probes/terminus.py` |
| 8 | **PASS**, 98 of 98 cases in 3 h 10 min; no network events | Evidence promoted as `makako-live-*` |

The manifest was refrozen after each source change (compose, the Terminus client, the probe). `make check` was rerun and the pre-gate manifest check passed before each attempt.

## Fixes made during implementation

- Unit tests hung because monkeypatched `_authorize` seams received an extra argument. This was fixed by the context variable.
- The first scan rule scanned tiny selections.
- The registry cache was corrupted by a caller that mutated a returned registry.
- M09a-T03 hit a token expiry while provisioning 120 resources on makako; it now fetches a fresh token per request.

## Limitations and open items

- **ChangeSet decisions are still per resource.** `_DecisionMemo` pre-fetching would reduce the 5,030 OpenFGA calls per load.
- **Unprofiled lookup cost.** The remaining 8 s per lookup on makako, about 3 s on the laptop, is unprofiled.
- **Scan cost.** The whole-store scan grows with total tuples; the round-trip rule falls back to per-resource reads for very large stores.
- **Review.** One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

Implement M10 from its plan, then revalidate M11 against the M10 report.
