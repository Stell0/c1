# TerminusDB `_system` layer growth: root cause of deadline-bound failures

Review date: 2026-09-29.

## Trigger

The sleep-guarded 79-case gate on the audited 350-input D21 source
(`run-sleep-guarded-live-gate.sh`) failed its first case with no host suspend
(suspended-since-boot counter unchanged at 12,171.940 s).
`tests/integration/m06/test_t04_historical_rescope.py:175` received 503
`C1-DC-012` (`time_budget`) for Carol's `GET .../history?limit=1`: one failed
in 890.59 s. See [log](sleep-guarded-live-integration.log),
[JUnit](sleep-guarded-live-junit.xml), [exit](sleep-guarded-live-exit.txt),
and [host record](sleep-guarded-live-host-suspend.txt). The same deadline had
failed in earlier D17–D19 attempts.

## Measurements (read-only unless stated)

Host was idle: 16 CPUs, load about 1.5, TerminusDB instantaneous CPU 1%.
Earlier `podman stats` readings of about 71% were lifetime averages.

Backend latency against the long-lived development database before compaction:

| Request | Latency |
|---|---|
| `GET /api/ok` without auth | about 2 ms |
| `GET /api/info` with basic auth | about 30 ms |
| `GET /api/db/admin` (two databases) | 243–341 ms |
| knowledge head (`count=0`) | 115–147 ms |
| workflow head (`count=0`) | 228–465 ms |
| per-document `GET /api/history` on a 12-commit database | 1,024–1,252 ms |

The storage directory held 4,104 layer entries (534 MB). Every live case
creates and drops isolated databases; each operation adds a layer to the
`_system` graph through which every request resolves its database. No
compaction had ever run, so each request paid a cost proportional to all
earlier test churn. That also explains the gradual slowdown of M06-T04 across
gates: 737 s, then 834 s, then 890 s.

## Intervention

`POST /api/optimize/_system` (the documented TerminusDB layer rollup; data is
unchanged) returned `api:success` in 2.5 s. Immediately afterwards:

| Request | Before | After |
|---|---|---|
| `GET /api/db/admin` | 243–341 ms | 4–7 ms |
| knowledge head | 128–147 ms | 52–53 ms |
| workflow head | 251–327 ms | 61–207 ms |

The unchanged T04 timing diagnostic then passed
(`run-sleep-guarded-t04-timing.sh`): one passed in 242.02 s, compared with
834–890 s before. Carol's history request (request 13) returned 200 in
624.742 ms, compared with 1,734–2,051 ms in earlier traces. See
[log](sleep-guarded-t04-timing.log), [phase JSON](sleep-guarded-t04-timing.json),
[JUnit](sleep-guarded-t04-timing.junit.xml), and
[exit](sleep-guarded-t04-timing.exit.txt).

## Durable fix

`tests/integration/conftest.py` adds an autouse fixture that runs the same
`_system` optimization after every live integration test when `C1_STACK=1`.
It runs in teardown, so it never overlaps a test's own requests or
measurements, and a failed compaction fails the test visibly. No product code,
assertion, deadline, limit, or authorization path changed. Product runtime does
not create or drop databases, so this churn comes from the test harnesses only.

The source is frozen as a 351-input manifest,
[`implementation-files-system-compaction.sha256`](implementation-files-system-compaction.sha256)
(file SHA-256 `ff19a4a7b4f0b6a179392f1404f6bb55d3f45f32195f260d42a64806fa405b02`).
It differs from the audited D21 manifest only by adding that conftest. Full
`make check` passed: 810 passed, 79 skipped, 17 warnings; Ruff and mypy (249
files), secrets, baseline, and profile checks passed. See
[check log](check-system-compaction.log).

## Relationship to earlier findings

This does not retroactively explain the two `RemoteProtocolError` disconnects,
and it does not change any earlier recorded result. The D17–D20 history and
entity-lookup optimizations remain in place; their measured phases were all
inflated by the same per-request floor.

## First gate on the 351-input source

`bash docs/evidence/M07/run-compaction-live-gate.sh` started 07:13:57 UTC and
terminated FAIL at 07:39:16 UTC with no host suspend: three passed, one
failed in 1,515.54 s; pytest 1, tee 0, restore 0, script 1. See
[log](compaction-live-integration.log), [JUnit](compaction-live-junit.xml),
[exit](compaction-live-exit.txt), [frames](compaction-live-failure-frames.jsonl),
and [host record](compaction-live-host-suspend.txt).

| Case | Before compaction (D21 gate) | This gate |
|---|---|---|
| M06-T04 | 834.216 s | 241.479 s, PASS |
| M07-T01 | 2,238.979 s | 676.640 s, PASS |
| M07-T02 | 6.600 s | 4.122 s, PASS |
| M07-T03 | 2,326.221 s | 592.849 s, FAIL |

M07-T03 failed while the fixture loader applied a ChangeSet:
`ChangeService._reconcile` called `FGA.bind`, whose OpenFGA `POST /write` hit
the unchanged 2.0 s client timeout (`httpx.ReadTimeout`, surfaced as
`FGAError: authorization service unavailable`). The OpenFGA server log records
that write completing in 2,099 ms. Across 326 writes since 07:00 UTC the
server-side median was 3 ms and the 99th percentile 873 ms, with a tail of
1,168, 1,410, and 2,099 ms. PostgreSQL, OpenFGA's datastore, logged a
checkpoint at 07:36 with a 1.512 s sync phase and one 0.937 s file sync.

Host state right after the failure: swap 4,194,300 kB total with 21,168 kB
free; memory available 3,842,316 kB; `/proc/pressure/io` full avg60 17.18%
and avg300 14.63%; TerminusDB had 136,344 kB swapped out. The largest resident
processes were browser processes outside the stack. This indicates host memory
and I/O pressure stalling datastore syncs. It is an environmental condition,
not a C1 code defect, and the 2.0 s authorization timeout was deliberately not
changed. The gate should be rerun after freeing host memory.

## Gate on makako.sf.nethserver.net

The 351-input source was copied to `/root/c1` on makako.sf.nethserver.net, a
DigitalOcean "Regular" VM with 4 vCPUs, 7.6 GB RAM, no swap, Rocky Linux 9.8,
and SELinux enforcing. The local secrets file was not copied; `make stack-up`
generated fresh credentials there. The two bind-mounted configuration
directories needed root ownership and the `container_file_t` label; the
compose file was not changed. The same four pinned images ran healthy. The
manifest check passed (351 inputs) and `make check` passed (810 passed, 79
skipped). See [manifest](manifest-check-before-makako-live.log) and
[check](check-makako.log).

`run-makako-live-gate.sh` failed its first case after 244.16 s: M06-T04 line 53,
the first document read after the rescope, returned 503 `C1-DC-012`. No host
suspend occurred. See [log](makako-live-integration.log),
[JUnit](makako-live-junit.xml), and [exit](makako-live-exit.txt). The
single-case timing diagnostic then failed after 2.41 s with
`FGAError: authorization service unavailable` during harness setup; see
[log](makako-t04-timing.log).

On that host OpenFGA recorded 422 ms for `CreateStore`, and PostgreSQL logged a
checkpoint writing 811 buffers in 81.1 s. TerminusDB head reads took about 63 ms
and authenticated info calls about 11 ms, similar to the compacted laptop
stack. The failures are consistent with slow VM storage and limited shared CPU
for the 2 s budgets, not with a code defect. The stack there was stopped with
its volumes retained.
