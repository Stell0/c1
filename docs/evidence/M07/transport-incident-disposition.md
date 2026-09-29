# M07 transport incident and acceptance disposition

The combined 79-case live run on the verified 345-input snapshot terminated
with a failure at
`tests/integration/m05/test_t01_directory.py::test_t01_directory_shared_identity_and_authorized_assertions`.
After the M05 backend-fetch test passed, HTTPX raised
`RemoteProtocolError: Server disconnected without sending a response`. The
terminal result remains 68 passed, one failed, 14 warnings in 13,675.26 s;
69 JUnit cases were recorded, with ten selected tests not run under `-x`.
Pytest exited 1, tee 0, evidence restoration 0, and the wrapper exited 1. The
failure is preserved in `corrected-live-integration.log`,
`corrected-live-junit.xml`, and `corrected-live-exit.txt`.

Read-only inspection of retained service logs did not establish a server-side
cause. OpenFGA had no matching error marker; the TerminusDB output could not be
time-correlated; and the Keycloak capture contained no lines. See
`original-transport-log-review.md`. These observations cannot prove that no
transient occurred. The original disconnect's underlying cause remains
unknown.

A separate instrumented M05 diagnostic subsequently passed all 12 unique
expected cases in 2,011.05 s with one warning. The case-check JSON reports
12/12 exact matches; pytest, tee, and the wrapper exited 0. The frame JSONL
contains only session start/finish markers because no test failed. The
345-input implementation manifest was verified unchanged after this
diagnostic. See `transport-diagnostic-m05.log`,
`transport-diagnostic-m05-junit.xml`,
`transport-diagnostic-m05-case-check.json`,
`transport-diagnostic-m05-exit.txt`, and
`manifest-check-after-transport-diagnostic.log`. This later pass neither
explains nor removes the original failed result.

Astra's review clarified that forensic proof of the transient cause is not a
separate acceptance requirement. After controlled stack recovery, a complete
run of the unchanged 79-case selection passes, and all remaining closure
checks pass, the original disconnect may be recorded as an operational
incident with cause unknown. This does not reclassify the original result,
assert that restart fixed the underlying cause, or permit a passing demo or
focused diagnostic to substitute for the full gate. If the disconnect recurs,
it is not disposed of as a single observed incident without further review.

## Current status

The root ran `bash docs/evidence/M07/run-transport-recovery.sh`. Stack-down and
stack-up, including tee/wrapper steps, exited 0 and retained volumes and
configuration. A bounded service-state check at 2026-09-28 20:24:25 UTC
reported one running container for each of the four services, exit code 0, and
`OOMKilled=false`. The first read-only image check failed with
`ModuleNotFoundError` because `PYTHONPATH` was omitted; the corrected check
matched all four configured image pins. The source manifest was verified
unchanged before the next gate. These observations do not establish the cause
of the original disconnect.

The root started `bash docs/evidence/M07/run-post-transport-live-gate.sh` at
2026-09-28 20:24:57 UTC after the 345-input manifest check passed. The runner
preserved the same 79 test paths and assertions and added only the reviewed
docs-only failure-frame hook. It terminated FAIL at the first M06-T04 test,
`tests/integration/m06/test_t04_historical_rescope.py:216`: expected HTTP 200,
got 503 `C1-DC-012` (`time_budget`). The run recorded one failure in 840.02 s;
78 selected tests were not run. Pytest exited 1, tee 0, evidence restoration
0, wrapper 1. The safe failure frames identify `AssertionError`, test function,
and line; M05 was not reached, so this is not a transport-disconnect recurrence.
See the [log](post-transport-live-integration.log), [JUnit](post-transport-live-junit.xml),
[exit](post-transport-live-exit.txt), and [frames](post-transport-live-failure-frames.jsonl).

The post-recovery run therefore does not meet the condition for disposing the
original M05 failure as a single operational incident. Its cause remains
unknown; recovery success does not establish a cause or fix. D19's unchanged
T04 timing attempt failed its deadline. D20's full local check and unchanged
T04 timing diagnostic passed, but its full 79-case gate later failed at
M04-T01. That request raised `httpx.RemoteProtocolError` during a TerminusDB
workflow-document GET in `_planned_records`, before ChangeSet intent. The run
ended with 54 passed, one failed, and 24 not run; its 348-input manifest
remained unchanged. This is a second transport disconnect in a different
operation. Neither incident's underlying cause is established, so the first
cannot be characterized as a single isolated occurrence. D21 implements one
immediate same-client/same-arguments retry only for GETs raising
`RemoteProtocolError` under the original deadline. Focused transport/guard
tests and static checks passed, and the corrected synthetic socket probe passed
all five cases. The initial probe and diagnostic failures were caused by the
helper's server/writer cleanup order and were corrected; they do not establish
a transport-retry failure. D21 is frozen at 350 inputs. The audited manifest
differs from the retained pre-audit manifest only in `.secrets.baseline`, after
a root-reviewed false positive for a dummy local-probe credential; scanner
filters were unchanged. Its corrected full local check passed (810 passed, 79
skipped, 17 warnings; Ruff 371, mypy 248, secrets 829, baseline/profile
passed). The six-case focused M04 service gate passed all six expected unique cases
in 504.33 s; pytest/tee/restore/script exited 0 and the audited manifest
remained unchanged. The full 79-case D21 gate is running, with nine passing
cases observed and no terminal result yet. M07 remains `IN_PROGRESS`, and the incident remains
undispositioned pending applicable live-gate and closure checks.

An unchanged timing-only T04 replay also failed at assertion line 175: one
failure in 767.98 s, with pytest 1, tee 0, and script 1. Its 13th request
returned 503 `C1-DC-012` in 2,046.947 ms; the handler was cancelled at
2,001.851 ms. The 345-input manifest remained unchanged. The phase record
narrows the late request timeline, but does not prove a root cause. D19 later
reuses the same head-bound immutable workflow manifest across index/planner
consumers to avoid three duplicate journal calls, with existing planner head
checks retained. It adds no FGA cache, does not change history-source selection,
and raises no limits. The D19 timing wrapper then failed. The D20 timing
diagnostic subsequently passed as one T04-only run, while the full 79-case gate
failed at M04-T01 with another `RemoteProtocolError`. D21 implements a bounded
GET retry and passed focused tests, the corrected synthetic probe, and audited
full local checks. The six-case focused M04 service gate passed; the complete
79-case D21 gate is running with nine passing cases observed so far. See the [timing review](history-performance-review.md)
for exact measurements; neither result alone disposes the M05 incident.

## Final status (2026-09-29)

The full 79-case gate passed on the final 351-input source (`final-source-resume-live-*`: 79 passed in 5,278.87 s, exact expected identities, all exits 0, no host suspend, manifest unchanged before and after) and on the D22 source (`deadline-live-*`). The fixture CLI, M01 probe, and no-AI demo passed, and the stack was stopped. Neither `RemoteProtocolError` recurred in the final runs. Their causes remain unknown, and because a second disconnect occurred earlier, the disposition requires owner review before they are closed as operational incidents. Root causes found for the later deadline failures were TerminusDB `_system` layer growth, a host suspend, and host swap exhaustion; see `system-compaction-review.md` and `m04-t06-rerun-review.md`. The [M07 report](../../milestones/M07-report.md) holds the acceptance matrix.
