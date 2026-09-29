# Guarded M06-T04 timing probe

The guarded timing probe completed the unchanged targeted integration test:
1 passed, exit 0, in 751.79 seconds. The launch command was
`bash docs/evidence/M07/run-guarded-history-probe.sh`; it unsets the six
provider-key variables and writes the dedicated timing JSON, JUnit, log, and
exit artifacts linked below. The script itself is retained at
[`run-guarded-history-probe.sh`](run-guarded-history-probe.sh).

- Timing data: [`m06-t04-timing-guarded.json`](m06-t04-timing-guarded.json)
- JUnit: [`m06-t04-timing-guarded-junit.xml`](m06-t04-timing-guarded-junit.xml),
  one testcase, zero failures/skips, exit 0
- Pytest log: [`m06-t04-timing-guarded.log`](m06-t04-timing-guarded.log)
- Captured process statuses: [`m06-t04-timing-guarded-exit.txt`](m06-t04-timing-guarded-exit.txt),
  pytest 0 and tee 0

The JSON records 16 document requests, including five history requests: three
returned 200 and two returned 409. Request 13 returned 200 and had the longest
history operation: `document_history_total` 1,954.934 ms; its enclosing request
took 1,997.916 ms. In that request the observed phase starts were
`historical_cohort_fetch` at 1,437.732 ms, `final_authorization_guarded` at
1,645.489 ms (351.714 ms duration), then `workflow_head` at 1,838.384 ms
(158.774 ms duration). These nested phase durations overlap and must not be
added. This trace reports instrumented timing only; it does not alone prove
the knowledge-read barrier or imply a sustained latency guarantee.

Across the five history requests, the instrumented starts showed
`historical_cohort_fetch` before `final_authorization_guarded` in three
requests returning 200 and one returning 409. The other 409 returned before
either hook was reached. In the four requests reaching both hooks, the later
`workflow_head` phase was the final recorded phase. This describes observed
phase instrumentation only and does not infer why either request returned
409.

Before the final gate, the guarded 344-input manifest was rehashed against
current files: all 344 matched. The old 339-entry
`implementation-files.sha256` exactly matched
`implementation-files-before-history-fix.sha256`; it was preserved as
`implementation-files-corrected-m07.sha256`. Then the main manifest was
refreshed from the guarded manifest. The verification command
`python3 docs/evidence/M07/verify-manifest.py` exited 0 and reported
`PASS: 344 frozen implementation inputs unchanged`; see
[`manifest-check-before-final-live.log`](manifest-check-before-final-live.log).
