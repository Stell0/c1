# M07 bounded performance-change review

Reviewed on 2026-09-28 against the working tree based on `7c1c7e6`.
Reviewer: independent delegated architecture/security advisor. This was a
source and test inspection, not a test execution or live-service verification.
Only this review note was written by the reviewer.

## Scope and outcome

No blocking authorization, identity, or cancellation issue was identified in
the reviewed changes to `src/c1/query/compile.py`,
`src/c1/storage/schema.py`, `src/c1/query/plan.py`, and
`src/c1/context/service.py`. Startup index warming was not implemented and is
not part of this assessment. The configured two-second limit remains intact.

- **Selective numeric fallback:** GraphQL validates every returned row's
  requested backend ID, canonical ID, type membership, and identity uniqueness
  before decoding literals. Recognized numeric lexical coercion selects only
  the affected requested records for document GET. Other detected shape errors
  retain whole-chunk fallback. GETs use the same immutable commit and validate
  canonical identity, registered primary class, and storage identity. No
  numeric lexical spelling is reconstructed from a JSON number.
- **Fresh profile authority:** Schema and marker reads remain fresh on every
  call. Missing or mismatched authority fails closed. Their overlap with
  preauthorized-ID record reads does not make records available to callers
  until every authority and retrieval task succeeds. These network reads,
  including fallback GETs, share the same semaphore (eight by default).
- **Selection authorization:** Scope listing and the binding snapshot overlap
  only after the initial workflow-head read. Snapshot bracket checks, fresh
  per-resource permission and current-binding checks, and the final build head
  check remain. Publication still reauthorizes the original plan between two
  further workflow-head checks. No positive authorization cache was added.
- **Context revision and cancellation:** Current knowledge-head resolution can
  overlap selection, but retrieval starts only after both succeed and uses the
  resolved commit. Pinned revisions skip current-head resolution while still
  obtaining current authorization. Failure and timeout paths cancel and await
  sibling work; no partial package is returned after failed finalization.

## Focused test inspection

Inspected these test files without executing them:

- `tests/unit/m07/test_compile_fallback.py`: precise lexical preservation,
  malformed/unrequested/duplicate row fallback, wrong returned identity,
  shared bounds, and cancellation cleanup.
- `tests/unit/m07/test_profile_reads.py`: fresh authority, missing/mismatched
  schema or markers, shared bounds, failure/timeout cleanup, and rejection
  after a previously successful marker check.
- `tests/unit/m07/test_fetch_authority.py`: results withheld until authority
  succeeds, failure/timeout cleanup, and one shared gate across authority,
  GraphQL, and document fallback.
- `tests/unit/m07/test_plan_concurrency.py`: initial-head ordering, failure and
  timeout cleanup, fresh permission checks with a cached projection, and
  rejection of workflow-head changes.
- `tests/unit/m07/test_service.py`: context head/selection overlap, sibling
  cleanup, pinned revision behavior, and finalization preventing publication.

## Closure limits

This review does not establish real-service latency, backend atomicity, or
the M07 acceptance gate. The reported fixture-demo success and regression
counts were not independently executed here. Retain their exact commands and
results in the milestone evidence, and run the planned T01–T07 gates without
raising the deadline or bypassing fresh authorization. Subsequent code changes
require an appropriate follow-up review.

## Follow-up: applied cold-request reduction

The advisor inspected the subsequently applied `/tmp/c1-m07-cold-fix.patch`
and the actual source and focused tests. The patch checksum matched the
milestone lead's supplied checksum. No blocking issue was identified in this
bounded follow-up; no production source was edited by the reviewer.

- `CurrentBindingIndex.snapshot` retains its initial check for ordinary callers.
  The new private `_snapshot_after_head` has exactly one production caller:
  `AuthorizedSelection._build`, after its fresh workflow-head read. Cold
  enumeration still checks the head afterward. A cached projection obtained
  after waiting for the index lock cannot reach knowledge retrieval until fresh
  resource authorization and the build's exact-head check succeed. Finalization
  retains fresh authorization bracketed by head checks.
- Entity queries overlap revision resolution and selection only when neither a
  cursor nor a revision is supplied. Retrieval waits for both results. The
  original deadline bounds the overlap; failure, timeout, and external
  cancellation cancel and await siblings. Non-timeout failures propagate.
  Cursor decoding remains first on continuation requests, preserving invalid
  cursor precedence; pinned and cursor-bound requests do not read current head.
- Inspected `test_cold_index.py` for cold enumeration mutation, cold and cached
  lock-wait mutation, default-method guards, fresh permission checks, and
  revocation at finalization. Inspected `test_entities_concurrency.py` for
  retrieval barriers, sibling cleanup, timeout/external cancellation, original
  failure propagation, invalid cursor precedence, and pinned/cursor ordering.
  These tests were not executed by the advisor.

The milestone lead reports that the first complete live run failed T01 with
`C1-QY-053` and T03/T07 with `C1-CX-014`, with four other tests passing. This
inspection neither replaces that failed evidence nor establishes a successful
rerun. The unchanged two-second limit and the planned real-service gate still
require execution against the updated implementation.

## Follow-up: finalization overlap

The advisor inspected the applied `AuthorizedSelection.finalize` change and
`tests/unit/m07/test_finalize_concurrency.py`. No blocking issue was found.
Fresh authorization starts alongside the first head read, using the original
plan's resource IDs and scope bindings. The first head is awaited and compared
before consuming authorization success or failure; the final head comparison
still occurs after successful authorization. No head check or live permission
or binding check was removed.

Explicit task cleanup preserves first-head mismatch/error precedence over a
completed authorization failure and cancels and awaits unfinished authorization
on failure, timeout, or external cancellation. The existing absolute deadline
and error mappings remain. This relies on the existing supported-write rule
that security mutations establish their workflow barrier before changing FGA.

The focused tests inspected cover overlap, waiting for the final head,
first-head precedence over both completed and running authorization failures,
authorization denial/failure, final-head mutation, and timeout/external
cancellation in all three phases. The advisor did not execute these tests or
the live probe. This source review makes no latency or passing-gate claim;
the previously reported cold-request timeout remains unresolved by evidence
until an appropriate successful execution is recorded.
