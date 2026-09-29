# Post-transport instrumented 79-case gate — review and execution status

This document records the wrapper review prepared after the original M05 transport failure. At preparation time, the focused diagnostic and wrapper had not executed; the subsequent diagnostic and active full-gate result are recorded below. The source, tests, and deployment inputs remain unchanged from the verified 345-input snapshot. No attempt is made to infer that recovery fixed the unexplained disconnect.

The lead's steering retained `c1_m07_transport_frames.py` byte-for-byte and moved future behavior into `c1_m07_transport_frames_full.py`. Before that steering, the originally requested `c1_m07_transport_frames_diagnostic_snapshot.py` had already been created from the exact diagnostic hook bytes; both original and snapshot remain at:

```text
bdc41e16749d7fc80d7c97d2a2b9a835461051e3b187f19f7d6f2d65e42bedcd
```

The active diagnostic wrapper also remains at `5c32d0b538619ae6f421f353c6949e82b36166482145dad04ee803657ea82f28`. No active-process hook module was reloaded or patched.

## Failure-frame hook design

The full plugin copies the reviewed bounded metadata policy and adds `--c1-m07-failure-frames`. Its unchanged default is the original diagnostic JSONL filename, but the future wrapper explicitly supplies a different filename. Relative paths are interpreted under the repository root. Targets must be new `.jsonl` files directly inside `ROOT/docs/evidence/M07`, with an unchanged resolved parent; existing paths, destination symlinks, and parent redirection are rejected. Creation uses `O_EXCL | O_NOFOLLOW` and mode 0600 before test setup.

All integration exceptions from setup/call/teardown are captured before default traceback formatting. Data remains limited to test identity/phase, exception classes/chain relationships, frame filename/function/line number, truncation markers, and allowlisted HTTP method plus fixed backend label for known HTTP loopback ports. URL path/query, full URLs, bodies, headers, error text/repr, source snippets, locals, and arguments are excluded. Unknown request destinations are omitted. Successful tests perform no new diagnostic I/O; session markers and failure records are flushed/fsynced. No client method, request, timeout, assertion, retry, or authorization work is modified.

## Reviewed wrapper

`run-post-transport-live-gate.sh` retained the corrected gate's exact test path sequence: M06-T04 once, M07, the other six M06 files, then M01–M05. A static comparison confirmed the arrays are identical. It retained `-q -x`, `--tb=line`, `--show-capture=no`, the existing diagnostics plugin, no pytest cache, six provider keys unset, and offline UV with `.uv-cache`. It added only the docs-only plugin path, `-p c1_m07_transport_frames_full`, and the explicitly named JSONL destination. The wrapper retained the same 79 unique test paths and assertions. Its terminal FAIL is recorded below.

New evidence destinations are:

- `post-transport-live-integration.log`, `post-transport-live-junit.xml`, `post-transport-live-exit.txt`, and `post-transport-live-failure-frames.jsonl`.
- `post-transport-generated-m01-inventory.json`, `post-transport-generated-m01-inventory.md`, and `post-transport-generated-m03-api.log` when the protected evidence changes.

Every destination is checked for an existing path or dangling symlink before execution. The EXIT trap preserves changed generated evidence and restores only the original M01 inventory files and M03 API log. Unexpected protected symlinks/non-regular objects fail restoration rather than being followed. Generated destinations are checked again before copying; failed restoration keeps the backups. Pytest, tee, restoration, and script exits remain independent. Earlier gate failures and diagnostic results are not overwritten or combined into a new passing result.

Command started after diagnostic and review:

```text
bash docs/evidence/M07/run-post-transport-live-gate.sh
```

## Static checks

Each named command exited 0:

```text
bash -n docs/evidence/M07/run-post-transport-live-gate.sh
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python -m py_compile docs/evidence/M07/c1_m07_transport_frames_full.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff check docs/evidence/M07/c1_m07_transport_frames_full.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff format --check docs/evidence/M07/c1_m07_transport_frames_full.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked mypy --strict docs/evidence/M07/c1_m07_transport_frames_full.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python docs/evidence/M07/verify-manifest.py
```

At preparation time, the manifest check reported 345 frozen implementation inputs unchanged. A stdlib-only comparison confirmed identical gate path arrays, unchanged diagnostic hook/wrapper hashes, and an exact snapshot. Reviewed no-index diffs had the expected difference exit status; whitespace checks produced no diagnostics. No collection, plugin invocation, live service request, or full gate had run at that stage.

Final SHA-256 values:

```text
91a8c51af74aa77a44875c9dd8b0830e6dea5cf9b31a38d01d617dacd26b870c  c1_m07_transport_frames_full.py
c6aca42b352a7cf3a879afccab09a0c57a8889b0c0d15c4e991ab0bb31ad07e8  run-post-transport-live-gate.sh
```

The run terminated FAIL at the first selected M06-T04 case,
`tests/integration/m06/test_t04_historical_rescope.py:216`: expected HTTP 200,
got 503 `C1-DC-012` (`time_budget`). It recorded one failed test in 840.02 s;
78 selected tests were not run. Pytest exited 1, tee 0, evidence restoration
0, and the wrapper exited 1. The [JUnit](post-transport-live-junit.xml)
contains one failed case; the [safe failure frames](post-transport-live-failure-frames.jsonl)
record `AssertionError`, test identity, and source line. M05 was not reached,
so this run does not reproduce the earlier HTTPX disconnect. The pre-run
manifest check verified 345 inputs unchanged. The original M05 transport cause
remains unknown, and successful recovery does not prove its cause.

## Status after M05 diagnostic and review

The focused instrumented M05 diagnostic completed after this wrapper was
prepared: 12/12 expected unique cases passed in 2,011.05 s, exit 0; see
`transport-diagnostic-m05-review.md`. Astra clarified that proving the
underlying transient cause is not a separate acceptance check. A controlled
stack down/up with retained volumes, followed by a terminally passing complete
79-case gate and all remaining closure checks, may dispose the original
disconnect as an operational incident with its cause unknown. This does not
claim the recovery fixes the cause and does not alter the original failure
record.

Controlled recovery completed: stack-down/up and their tee/wrapper steps
exited 0, retained volumes, and restored all four services to running state.
The corrected read-only check matched all four pinned images. The 345-input
manifest check passed before this full-gate launch. The root started
`bash docs/evidence/M07/run-post-transport-live-gate.sh` at 2026-09-28
20:24:57 UTC. Its test paths/assertions matched the original 79-case command,
with only the reviewed docs-only failure-frame hook added. The current concrete
blocker is the M06-T04 history timeout. D19 has since added bounded, head-bound
workflow-manifest sharing and passed local verification; the unchanged timing
run will test its effect. No performance improvement is claimed. M07 remains
`IN_PROGRESS` until the full gate and other
closure checks pass.

The unchanged timing-only follow-up also failed the same M06-T04 case at line
175 (one failed in 767.98 s). Request 13 returned 503 `C1-DC-012` in 2,046.947
ms, with the handler cancelled at 2,001.851 ms; the final workflow-head read
started at 1,910.405 ms and was cancelled after 135.607 ms. The 345-input
manifest was unchanged after the run. This narrows the late phase timeline but
does not establish a root cause. D19 later shared the same head-bound immutable
workflow manifest across planner/index consumers to avoid three duplicate
journal calls. Its local check passed, but the D19 timing wrapper also failed
the unchanged T04 deadline; duplicated calls are not established as the sole
root cause. D20 implements independent fresh cohort schema/profile/all-markers
authority work overlapped with history-metadata reads. Its full local check and
unchanged T04 timing diagnostic passed; the 348-input manifest remained
unchanged after timing. The subsequent full 79-case live gate failed at
M04-T01 with a second `RemoteProtocolError`; its cause is not established. D21
implements one bounded GET retry and passed focused checks, the corrected
synthetic socket probe, and audited full local `make check`. The six-case
focused M04 service gate passed all six expected unique cases in 504.33 s,
with all exits 0 and the audited manifest unchanged. The full 79-case D21
gate is running, with nine passing cases observed and no terminal result yet. See
the [performance review](history-performance-review.md). These results do not
close the M07 gate.
