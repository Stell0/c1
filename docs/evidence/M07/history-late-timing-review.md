# Later document-history timeout — timing preparation only

The distinct post-transport gate remains FAIL: its first M06-T04 case failed at test line 216 after about 840 seconds of whole-test execution; the other 78 cases were NOT_RUN. The failure was HTTP 503 with `C1-DC-012`, not a new observed HTTP stream disconnect. The safe frame artifact contains only the resulting test AssertionError; it does not expose the internal timed-out service phase. Earlier failure and timing artifacts are preserved.

## Exact request and limits of the evidence

`tests/integration/m06/test_t04_historical_rescope.py:213–216` sends Carol's GET document history with limit 100 after a readable part has moved from Handbook to Notes and then been edited in Notes. The response must include the move-out revision but exclude that subsequent edit. This is timing ordinal 15. The earlier cursor-page request at lines 172–175 was ordinal 13, before the later edit. Reaching line 216 establishes that the cursor page succeeded and ordinal 14's stale cursor was correctly rejected with 409 / `C1-DC-014` at lines 211–212. The later grant-revocation hook at line 225 onward was not reached.

`src/c1/api/routes/documents.py:41–42` maps raw TimeoutError to `C1-DC-012`. `DocumentsService.history` sets one absolute two-second deadline, gathers current knowledge head, fresh selection, and workflow manifest; overlaps authorized current fetch with resource history metadata; fetches bounded historical snapshot cohorts; assembles attachment history; and executes guarded finalization. The observed code cannot distinguish expiry of that service timeout from expiry while the final knowledge-head precondition is pending. Query selection/fetch and finalization after a completed precondition normally translate their own budget failures to `C1-QY-053`, but nested cancellation timing prevents using the public code alone as precise phase evidence.

The earlier passing `m06-t04-timing-guarded.json` measured ordinal 15 at 1782.782 ms total, with document history at 1748.798 ms. Its workflow manifest took 537.384 ms; authorized current fetch 243.054 ms overlapped resource metadata (maximum 679.657 ms); historical cohort took 213.135 ms; guarded finalization took 312.832 ms. Its current-binding snapshot was warm (0.013 ms), following the stale-cursor request. Those are historical measurements, not measurements of this new failure. Ordinal 13 in that same earlier artifact was also close to the budget: document history 1954.934 ms. Test-wide 840 seconds cannot locate a two-second request's bottleneck.

## Prepared reproduction

The existing `c1_m07_t04_timing.py` already supports `--c1-t04-timing-output`; its source is unchanged at SHA-256 `3753e9408c8799a8b0bd4d1a2a9a048d60c7a24568210a94320942022b386148`. No copied or modified plugin is necessary. It records safe endpoint templates, test callsite/ordinal, status/allowlisted C1 code, and phase start/duration/outcome without request identifiers, arguments, credentials, response content, exception text, or headers. Its wrappers preserve return values, failures, and cancellation, and do not alter deadlines or authorization decisions.

After lead review only:

```text
bash docs/evidence/M07/run-history-late-timing.sh
```

The new wrapper runs only the unchanged named M06-T04 test, with the existing diagnostics and timing plugins, `-q -x`, `--tb=line`, `--show-capture=no`, and no pytest cache. Six provider-key variables are unset; UV is offline with `.uv-cache`. Destinations are `history-late-timing.log`, `history-late-timing-junit.xml`, `history-late-timing-exit.txt`, and `history-late-timing.json`. Every existing destination, including dangling symlinks, is refused. The timing plugin's final JSON creation is exclusive. The wrapper preserves pytest/tee/script exits separately. The test does not generate the protected M01 inventory or M03 API report, so no evidence restoration is added.

## Bounded source follow-up

No production algorithm change is justified by the new evidence yet. The timing result should identify the last started/completed phase of ordinal 15 and compare the critical path with the earlier passing ordinal 15. Specifically:

- If `resource_history_metadata` dominates, inspect `DocumentsService.history`'s `resource_history` loop and `HistoryService._fetch_metadata`'s shared eight-slot gate and storage-class probes. Complete creation/type hints already narrow known resources; unknown origins must retain all-class coverage. The candidate manifest alone cannot replace historical attachment checks or exclude the Notes edit.
- If `historical_cohort_fetch` dominates, inspect `fetch_record_snapshots` and `_fetch_records_content`: cohorts already share one fresh profile-authority read, use at most eight revisions, and apply complete hints. Any narrower fetch must retain unknown-class coverage, current authorization, exact historical decoding, and reference projection.
- If `final_authorization_guarded` dominates, retain `AuthorizedSelection.finalize_after`'s knowledge precondition, fresh per-resource binding/grant checks, and final workflow read after all three initial checks. These barriers cannot be dropped or moved earlier to save time. The current timing hooks distinguish fresh authorization and workflow reads; a remaining knowledge-head ambiguity would require a separate bounded timing hook rather than a speculative fix.

The lead owns any algorithm choice after phase evidence. No deadline increase, retry, skipped assertion, positive authorization cache, or weakened barrier is proposed.

## Static checks executed

Each exited 0:

```text
bash -n docs/evidence/M07/run-history-late-timing.sh
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff check docs/evidence/M07/c1_m07_t04_timing.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff format --check docs/evidence/M07/c1_m07_t04_timing.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked mypy --strict docs/evidence/M07/c1_m07_t04_timing.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python docs/evidence/M07/verify-manifest.py
```

The manifest reported all 345 frozen implementation inputs unchanged. The new-wrapper no-index whitespace check returned 1 for the new-file difference with no diagnostics. Wrapper SHA-256:

```text
6b8662932c31297c9169723b1da98ad897a7f5348ff4fd0d30214ab8c44134c5
```

No live test, service operation, API request, plugin execution, or wrapper execution occurred during this preparation. The failing subphase and future timing outcome remain unknown / NOT_RUN.
