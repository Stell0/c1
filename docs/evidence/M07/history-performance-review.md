# M06 document-history performance review

**Status:** D20's unchanged T04 diagnostic passed, but its 79-case gate later failed at M04-T01 with a second `RemoteProtocolError`. D21 is implemented, passed focused tests/static checks and a corrected synthetic socket probe, and its audited 350-input source passed corrected full `make check` (810 passed, 79 skipped, 17 warnings; Ruff 371, mypy 248, secrets 829, baseline/profile passed). The six-case focused M04 service gate passed all six expected unique cases in 504.33 s with all exits 0. The full 79-case D21 gate is running, with nine passing cases observed and no terminal result yet.
This note records an evidence-led follow-up from the M01–M06 regression gate.
The guarded T04 timing-only diagnostic passed historically, but later D19
shared-manifest timing failed the same deadline. Neither diagnostic is the full
regression gate, and M07 is not closed.

## Reproduced failure

The complete earlier-services regression run exited 1 with 71 passed, one
failed, and 14 warnings in 7,887.74 s. Its failing case was
`tests/integration/m06/test_t04_historical_rescope.py::test_t04_rescoped_part_disappears_from_old_document_views` at line 174. After
moving P3 out, Carol's `GET /v1/documents/{document_id}/history?limit=1`
expected HTTP 200 but received 503 `C1-DC-012` (`time_budget`). The
timing-only rerun used unchanged T04 and failed the same assertion: one failed
in 619.25 s, exit 1. The first-suite and focused-run logs, JUnit files, exit
records, and the before-history-fix 339-input manifest are retained in this
directory.

The timing trace identifies the 13th request as the failing history GET. It
returned 503 at 2,045.525 ms against the 2,000 ms request deadline; request
start was approximately 42.5 ms. The `document_history_total` span was
cancelled at 2,002.224 ms. Authorization selection took 669.559 ms; the
initial authorized fetch took 309.806 ms, including 308.488 ms of fresh
schema/profile-marker authority. Eight history-metadata reads completed around 1,446 ms.
Three historical fetches then took 230.311, 277.354, and 282.674 ms, each
accompanied by a fresh schema/profile-marker authority check of 229.660,
275.285, and 279.299 ms in the measured pre-optimization path; concurrent
GraphQL chunks took 63–109 ms. Snapshots completed around 1,729 ms, followed
by approximately 150 ms of sequential knowledge-head work. Final
authorization began at 1,879.704 ms and was cancelled at the deadline.

These phase intervals overlap. Their durations must not be added as if they
were sequential stages. The trace supports collecting one current
schema/profile-marker authority check for a bounded revision cohort before
content collection starts; it does not justify weakening per-resource
authorization or the security barrier, or increasing the configured deadline.

## Cohort timing rerun

The unchanged T04 timing-only cohort rerun also failed at the same assertion
(`tests/integration/m06/test_t04_historical_rescope.py:174`): one failed in
701.39 s, exit 1. The retained [log](m06-t04-timing-cohort.log),
[phase JSON](m06-t04-timing-cohort.json), [JUnit](m06-t04-timing-cohort-junit.xml),
and [exit record](m06-t04-timing-cohort-exit.txt) show request 13 returning
503 `C1-DC-012` in 2,051.654 ms against the original 2,000 ms deadline; the
`document_history_total` span was cancelled at 2,002.095 ms.

On this attempt, document selection took 1,114.835 ms, including
867.221 ms of authorization selection. The initial authorized fetch took
246.247 ms and included 228.730 ms of fresh profile authority. Eight history
metadata reads were issued together; the slowest took 512.606 ms and completed
around 1,676.545 ms. One fresh cohort authority check then took 202.636 ms,
with no repeated authority check per historical revision. Compared with the
prior trace's three authority checks accompanying the historical fetches, this
removes duplicated cohort-level work in the observed request. It does not
establish a successful response: the request still reached its deadline before
final resource authorization could complete. Selection and metadata phases
were slower in this run; the trace does not establish why, so no CPU or memory
cause is inferred. The separate [resource snapshot](resource-snapshot.txt) is
one read-only sample and makes no memory-pressure or causal claim.

## Prefetch timing rerun and guarded finalization refinement

The third unchanged T04 timing attempt also failed at line 174: one failed in
692.74 s, exit 1. Its [log](m06-t04-timing-prefetch.log),
[phase JSON](m06-t04-timing-prefetch.json), [JUnit](m06-t04-timing-prefetch-junit.xml),
and [exit record](m06-t04-timing-prefetch-exit.txt) show request 13 returning
503 `C1-DC-012` in 2,047.212 ms. Authorization selection took 738.422 ms;
the current-binding-index read took 397.522 ms. The authorized fetch took
670.455 ms, including a 627.406 ms profile-authority check queued behind the
eight metadata reads; the cohort fetch took 216.001 ms. Final authorization
began at 1,832.535 ms. Its concurrent initial workflow-head check took
177.776 ms; the last workflow-head check started at 2,010.361 ms and was
cancelled. These intervals overlap and must not be summed.

The M07 `AuthorizedSelection.finalize_after` implementation refines scheduling
for history publication without changing M06 D9 acceptance. It overlaps only
knowledge-head equality, fresh authorization of the original complete plan,
and the initial workflow-head read; knowledge-head errors take precedence. The
last workflow-head read starts only after all three succeed, and publication
requires the exact plan/head match. On failure, timeout, or cancellation, all
owned tasks are awaited. Authorization is not cached across requests, and
ordinary finalization remains unchanged. This is distinct from overlapping
whole-request finalization with a delayed last head, which remains rejected.

Focused verification recorded 25 guard-specific plus 20 related tests passed
(45 total), 139 history tests passed, and scoped Ruff/mypy passed. Astra's
source/test review found no blocker; the reviewer did not execute tests. The
first guarded full local check failed only Ruff formatting in
`src/c1/query/plan.py`; a second attempt failed M03 socket-permission tests in
the sandbox (15 failed, 673 passed, 80 skipped). The permitted corrected local
check passed (689 passed, 79 skipped, 17 warnings; exit 0; Ruff 339 files,
mypy 242 source files, secret scan 676 files, baseline/profile checks passed).
The guarded wheel has 117 entries and the run input manifest has 344 paths.
These local checks and review do not verify the history endpoint. The guarded
T04-only timing diagnostic later completed with one passing test; the final
combined live gate still failed at M07-T01 after M06-T04 passed. Current entity
lookup diagnosis is pending, and the applicable live gate has not passed.

## Accepted bounded design

For one request, group at most eight explicitly pinned history revisions into
a bounded cohort. Perform exactly one fresh, complete current schema/profile
and all-markers authority check for that cohort—not one such check per
revision. Do not reuse the initial selection read for this check or cache it
across requests. Every ordinary history record still receives its mandatory
fresh per-resource authorization; that resource authorization is separate
from the cohort's schema/profile-marker authority check. The cohort and any
fallback reads share the existing backend gate of eight. Decode, project, and
handle collisions independently for each revision.

Start the cohort's current schema/profile authority task before content
collector work. Return no result until that authority check and every required
snapshot have succeeded. If a task fails or the request is cancelled, cancel
and await its siblings. Preserve the original complete resource permission
plan and the M06 D9 publication barrier.

## Rejected overlap

The first M06 D9 review described the captured knowledge-head check followed
by security finalization as sequential. The current M07 history-only
`AuthorizedSelection.finalize_after` refinement has a scoped schedule: overlap
knowledge-head equality, fresh authorization of the original complete plan,
and the initial workflow-head read, with knowledge-head errors taking
precedence; start the last workflow-head read only after all three succeed,
then require exact plan/head equality for publication. This preserves the M06
D9 barrier while avoiding the earlier sequential schedule. Do not run
whole-request `_finish` / security finalization concurrently with the delayed
last workflow-head read: finalization could complete before that wait, letting
an intervening rescope with unchanged knowledge escape the post-wait security
barrier. Failure, timeout, and cancellation must await all owned tasks.

## Evidence and remaining verification

- [Full M01–M06 first-run log](m01-m06-first-integration.log), [JUnit](m01-m06-first-junit.xml), [exit](m01-m06-first-exit.txt)
- [Focused unchanged T04 log](m06-t04-timing-first.log), [phase trace](m06-t04-timing-first.json), [JUnit](m06-t04-timing-first-junit.xml), [exit](m06-t04-timing-first-exit.txt)
- [Unchanged T04 cohort timing log](m06-t04-timing-cohort.log), [phase trace](m06-t04-timing-cohort.json), [JUnit](m06-t04-timing-cohort-junit.xml), [exit](m06-t04-timing-cohort-exit.txt)
- [Unchanged T04 prefetch timing log](m06-t04-timing-prefetch.log), [phase trace](m06-t04-timing-prefetch.json), [JUnit](m06-t04-timing-prefetch-junit.xml), [exit](m06-t04-timing-prefetch-exit.txt)
- [Guarded T04 run script](run-guarded-history-probe.sh), [log](m06-t04-timing-guarded.log), [phase JSON](m06-t04-timing-guarded.json), [JUnit](m06-t04-timing-guarded-junit.xml), and [exit](m06-t04-timing-guarded-exit.txt); one timing-only test passed
- [Final live-gate script](run-final-live-gate.sh), [344-input manifest verification](manifest-check-before-final-live.log), [live log](final-live-integration.log), [JUnit](final-live-junit.xml), and [exit](final-live-exit.txt)
- [Guard timing hook review](timing-plugin-guarded-review.txt), [344-input manifest](implementation-files-guarded-probe.sha256), [wheel check](wheel-guarded-check.md)
- [Read-only resource snapshot](resource-snapshot.txt); one sample only, no causal or memory-pressure claim
- [Before-history-fix input manifest](implementation-files-before-history-fix.sha256)
- [M06 D9 contract](../../milestones/M06.md)

The cohort and prefetch attempts timed out. The guarded finalization refinement
passed its focused and permitted local checks and has no Astra review blocker.
Its unchanged timing-only T04 diagnostic passed one test in 751.79 s (exit 0),
with request 13 returning HTTP 200 in 1,997.916 ms. This is a diagnostic pass,
not the full regression gate. The final live gate started after verification of
the 344-input manifest and failed after 2,749.06 s: M06-T04 passed, then M07-T01
failed at line 83 with 503 `C1-QY-053`; `-x` stopped before later tests. The
timing hooks record intervals only, without identifiers or payloads.
Whole-request finalization overlap remains rejected. Cold entity lookup
diagnosis, applicable reruns, M01 probe, final review, and stack-down remain
required. The corrected M07 T01–T07 suite passed separately on its earlier
snapshot; it does not close the full regression gate.

## Cold entity lookup follow-up (diagnostic passed; live verification pending)

The final combined gate failed at M07-T01 with cold Tesla entity lookup returning
503 `C1-QY-053` just beyond the unchanged 2,000 ms budget. A read-only
two-request phase probe recorded cold failure at 2,002.195 ms and warm success
at 1,396.833 ms; the initial current-binding-index phase took 397.102 ms on the
cold request and 0.012 ms warm. Full phase evidence is retained in
[`entity-phase-first.json`](entity-phase-first.json) with its
[review note](entity-phase-first-review.md). Phase intervals overlap and are
not additive.

A separate one-process diagnostic set FGA fanout to 32 without changing the
production setting (16). It returned cold/warm HTTP 200 in 1,939.104/1,479.590
ms, while fresh authorization phases remained about 295–363 ms. The cold/warm
pair does not establish a causal or repeatable improvement over the production
setting, so the fanout experiment was not adopted. See
[`entity-phase-fga32.json`](entity-phase-fga32.json) and its
[review note](entity-phase-fga32-review.md).

The approved scoped implementation reads the initial workflow head, then runs
scope listing and private uncached index preparation in parallel. It then
performs fresh FGA/binding authorization, reads the mandatory exact workflow
head after authorization, and synchronously publishes the candidate with
compare-and-swap. This coalesces the redundant cold post-head read with the
required post-authorization workflow-head check; FGA has no workflow head. The
ordinary `index.snapshot` and standalone `snapshot_after_head` paths remain
unchanged.
The current-binding-index result is provisional until a compare-and-swap cache
generation publish, so a slower stale read cannot overwrite a newer cache
entry. Candidate-derived cap and global pending guards still use the exact
head before errors are published, and no oversized FGA request is sent. The
planner uses one private prepare-and-publish path under the existing controlled
workflow assumption; it does not cache authorization or rewind the head. Full
final authorization and final head guards remain required. The earlier and new
cold-index phase readings are 397.102 ms and 214.143 ms. Their roughly 183 ms
difference is observed, but separate samples and variation in other phases do
not isolate a causal saving or establish an SLA.

The initial provisional-index `make check` failed only because the new unit
test needed Ruff formatting. Its intermediate corrected run passed 715 tests,
79 skipped, and 17 warnings, but predates the cache-race repair. Astra found
that an ordinary snapshot read may await the journal while the private
provisional path publishes newer cache state. The repair also makes ordinary
snapshot writes and clears compare against their captured generation token.
Astra re-reviewed 12 race cases with no remaining blocker; the advisor did not
run tests or services. No authorization bypass was identified. Scoped test
groups (56 and 261) passed, and the corrected full local check passed with 727
tests, 79 skipped, and 17 warnings in 29.79 s; Ruff checked 347 files, mypy
243 source files, secrets 707 files, and baseline/profile checks passed. The
first Ruff-only failure, intermediate check, and CAS-repair check are retained
separately in `check-provisional-index*.log`.

The final read-only probe used production FGA concurrency 16, backend gate
eight, and the unchanged 2,000 ms budget. Cold and warm exact-label entity
queries both returned HTTP 200 in 1,813.570 ms and 1,351.835 ms. Each completed
225 FGA runtime calls; peak concurrency was 16, with zero calls left active or
cancelled. The earlier cold probe measured a 397.102 ms index read; the new probe measured
214.143 ms, an observed difference of about 183 ms. These separate single
observations, with variation in other phases, do not isolate a causal saving,
a stable latency margin, or an SLA. The earlier 344-input final-gate manifest
remains historical.
The 345-input implementation snapshot was verified before the corrected live
gate; the wheel has 117 entries (SHA-256
`1777fe25920584396d593020e7bb6bc94bc2660eb793d7207b157533cff1d4f3`). That
79-case run terminated FAIL after 13,675.26 s: 68 passed, one failed, and 14
warnings; the JUnit records 69 cases with zero skips/errors. M06-T04, all M07
cases, M06-T01 through T03 and T05–T07, and M01–M04 passed. M05 backend-fetch
passed, followed by M05-T01 failure with `httpx.RemoteProtocolError: Server
disconnected without sending a response`. Pytest exited 1 under `-x`, tee 0,
protected-evidence restoration 0, and wrapper 1. This is an undiagnosed
transport failure, not a `time_budget` result. 10 later selected tests did not run.
The source remains at the verified snapshot. The transient cause remains
unknown; forensic proof is not a separate acceptance requirement. A separate instrumented M05 run passed all 12 expected unique
cases in 2,011.05 s (one warning, pytest/tee/wrapper exit 0); its frame output
contains session markers only, so it does not explain the original failure.
The post-diagnostic manifest check found all 345 inputs unchanged. Controlled
stack down/up then exited 0 using retained volumes/configuration. A bounded
safe-state check found four running services with exit code 0 and no OOM kills;
the corrected read-only image check matched all four pins. The first image
check invocation failed because `PYTHONPATH` was absent and is preserved.
The post-recovery instrumented 79-case run started after the 345-input manifest
check passed and terminated FAIL at the first M06-T04 test, line 216:
`tests/integration/m06/test_t04_historical_rescope.py` expected HTTP 200 but
received 503 `C1-DC-012` (`time_budget`). It recorded one failure in 840.02 s;
78 selected tests were not run. Pytest exited 1, tee 0, evidence restoration
0, wrapper 1. The JUnit contains the single failed test and the safe failure
frames record its assertion and source location. M05 was not reached, so this
is not a recurrence of the earlier M05 HTTPX disconnect. This is a distinct
history-path timing failure; its phase evidence and repair decision are
pending. The original transport cause remains unknown. Overall live
verification remains `IN_PROGRESS`.

## Unchanged timing-only replay

An unchanged T04 timing-only replay also failed, with pytest exit 1, tee 0,
script 1; one failure in 767.98 s. The retained [log](history-late-timing.log),
[JUnit](history-late-timing-junit.xml), [phase trace](history-late-timing.json),
[exit record](history-late-timing-exit.txt), and
[post-run manifest check](manifest-check-after-history-late-timing.log) show
the 345-input source remained unchanged. The same test failed at its assertion
on line 175. Its 13th request returned 503 `C1-DC-012`; request elapsed time was
2,046.947 ms, and the history handler was cancelled at 2,001.851 ms. Selection
authorization took 683.202 ms; eight history-metadata reads ran with a maximum
observed duration of 756.933 ms; authorized fetch took 282.290 ms; the cohort
fetch took 210.985 ms. Guarded final authorization began at 1,699.074 ms. The
last workflow-head read began at 1,910.405 ms and was cancelled after 135.607
ms. These overlapping phase intervals describe the late request timeline; they
are not additive and do not, by themselves, establish why the history deadline
was exceeded. The later D19 change reuses the same head-bound immutable
workflow manifest across index/planner consumers, avoiding three duplicate
journal calls while retaining existing planner head checks. It adds no FGA
cache, changes no history-source selection, and raises no limits. The scoped
tests and corrected full local check pass; the T04 timing diagnostic later
failed, so this reuse did not establish a latency improvement. M07 remains
`IN_PROGRESS`.

## D19 shared-manifest timing run

The reviewed shared-manifest timing wrapper ran the unchanged T04 test against
the pinned services and retained the 2,000 ms budget. It failed at assertion
line 175 after 780.26 s (pytest 1, tee 0, script 1). Its 13th request returned
503 `C1-DC-012` in 2,039.592 ms; the history handler was cancelled at 2,002.087
ms. The request phases overlapped: selection authorization took 609.954 ms,
current fetch 255.548 ms, eight metadata reads had a maximum observed duration
of 774.090 ms, and cohort fetch took 234.787 ms (profile authority 234.446 ms).
The final guard started at 1,658.887 ms and was cancelled after 379.954 ms;
the final workflow-head read began at 1,870.845 ms and was cancelled after
167.952 ms. The 346-input post-run manifest check passed. These measurements do
not isolate a root cause; the full 79-case live gate was not run on this
source.

## Approved D20 direction

Root approved a bounded follow-up: start an independent fresh full
schema/profile-and-all-markers authority check after current-document and
bounds checks, overlapping it with history-metadata reads. The first
nonempty cohort awaits both that new authority check and its content; later
cohorts keep their fresh checks. This does not reuse the initial authority
check, add an FGA cache, change history-source selection, or relax limits.
Astra and the document-guard reviewer found no blocker. D20 is implemented in
the frozen 348-input source. Focused document-guard (87), selection preparation
(21), and broader tests (256) passed, as did scoped Ruff/mypy. The full local
check passed 780/79/17 in 29.27 s, with Ruff 366, mypy 246, secrets 792, and
baseline/profile checks passing. The reviewed unchanged T04 timing diagnostic
passed in 764.18 s (one test; pytest, tee, and wrapper exit 0). Request 13
returned HTTP 200 in 1,777.674 ms and request 15 in 1,592.162 ms; stale-cursor
request 14 retained its expected 409 `C1-DC-014` in 533.675 ms, and late-revoke
request 16 retained its expected 409 `C1-QY-051` in 1,198.172 ms. On request
13 the fresh profile-authority task started at 852.601 ms and took 572.456 ms
including waiting for the shared backend gate; its cohort read began at
1,286.942 ms and took 138.332 ms. On request 15 the authority task began at
639.516 ms and took 588.481 ms; cohort fetch began at 1,066.596 ms and took
161.677 ms. The new independent authority work overlapped metadata on both
requests, while expected negative checks remained intact. Phase variation means
these samples do not prove a causal latency improvement or guarantee a general
margin. All 348 inputs passed the post-run manifest check. The 79-case live gate
later failed on this frozen source at M04-T01 with a second
`RemoteProtocolError`; the D20 source remained unchanged after the run. This
does not establish the underlying cause. At the time this D20 run ended, D21's bounded GET retry was approved but not yet implemented; its later implementation,
checks, and current gate status are recorded in the status block above.

The later D19 shared-manifest timing attempt is preserved above and failed the
same T04 deadline. D20's diagnostic passed, but the full 79-case gate failed at
M04-T01 with a second transport disconnect. D21's narrow GET retry passed
focused checks and the corrected synthetic socket probe; its audited 350-input
source is frozen. The initial full local check failed on 15 loopback-dependent
tests with sandbox permission errors. A permitted-socket run then stopped only
at a dummy local-probe credential false positive; the audited baseline was
updated without scanner-filter changes, and the corrected audited full check
passed. The six-case focused M04 service gate passed. The complete 79-case D21
gate is running, with nine passing cases observed and no terminal result yet. The full 79-case gate was not run on the failed D19
source.
