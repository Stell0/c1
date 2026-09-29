# M04-T06 failure in the D21 79-case gate: host-suspend review and single-case replay

Review date: 2026-09-29. Source: audited 350-input D21 snapshot
(`implementation-files-read-retry-audited.sha256`), verified unchanged before
and after the replay.

## D21 gate failure timeline (UTC)

| Time | Event | Evidence |
|---|---|---|
| 01:57:15 | 79-case gate starts | `read-retry-live-junit.xml` suite timestamp |
| 06:03:22 | Laptop lid closed | host journal, `m04-t06-rerun-host-suspend.txt` |
| 06:03:23 | Host enters `s2idle` suspend; `user.slice`, including pytest, frozen | same |
| 06:23:11 | Lid opened; host resumes; `user.slice` thawed | same |
| 06:23:22 | M04-T06 records `KeyError: 'state'`; JUnit and frames written | file mtimes of `read-retry-live-junit.xml` and `read-retry-live-failure-frames.jsonl` |
| 06:23:23 | Runner writes exit record (pytest 1, tee 0, restore 0, script 1) | mtime of `read-retry-live-exit.txt` |

The failure was recorded 11 seconds after resume, following about 19 minutes 48
seconds of suspend in the middle of the M04-T06 case. Pytest reports durations
on a monotonic clock that excludes suspend, so the reported 14,785.75 s and the
case's 93.5 s do not include the suspended interval.

The test reads `response.json()["state"]` without first asserting the HTTP
status, so the failing status was not recorded. The safe failure frames contain
only the `KeyError` with no HTTPX request error, so this is not a transport
disconnect recurrence. The test reuses bearer tokens issued before suspend;
wall-clock token expiry across the suspended interval is consistent with a
rejected request returning a problem document without `state`, but the actual
status was not captured and this cause is not proven.

Keycloak and OpenFGA show a container start time of 05:44 UTC with zero
restarts and no OOM kill. That is before the suspend and consistent with the
deliberate stop/start in the M03-T07 outage case that ran earlier in the same
gate. TerminusDB and PostgreSQL were not restarted.

## Single-case replay

Command: `bash docs/evidence/M07/run-m04-t06-rerun.sh` (same pytest options,
plugins, and provider-key unsetting as the 79-case runner; selection is only
the failed node).

| Check | Result |
|---|---|
| Manifest before | PASS, 350 inputs ([log](manifest-check-before-m04-t06-rerun.log)) |
| M04-T06 | PASS, 1 passed in 205.23 s ([log](m04-t06-rerun-integration.log), [JUnit](m04-t06-rerun-junit.xml)) |
| Exit record | pytest 0, tee 0, manifest before 0, manifest after 0, script 0 ([exit](m04-t06-rerun-exit.txt)) |
| Host suspend during replay | none: suspended-since-boot 12,171.939 s before and 12,171.940 s after ([host record](m04-t06-rerun-host-suspend.txt)) |
| Manifest after | PASS, 350 inputs ([log](manifest-check-after-m04-t06-rerun.log)) |

## Disposition

The replay shows M04-T06 passes on the unchanged D21 source without a host
suspend. It does not convert the D21 79-case gate to PASS: 15 selected cases
were not run, and a focused replay cannot substitute for the complete gate. The
D21 gate result remains FAIL, attributed to an environmental host suspend by
timing correlation. M07 remains `IN_PROGRESS`. The next gate run should block
sleep and lid-switch handling for its whole duration and record the
suspended-since-boot counter before and after.
