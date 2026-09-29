# M05 transport failure frames — prepared, not executed

The corrected ordered gate ended with 68 PASS, one FAIL, and ten NOT_RUN cases. Its directory failure lasted 244.194 seconds and retained only `httpx.RemoteProtocolError` / `httpcore.RemoteProtocolError` text because traceback formatting was `--tb=line` and captured output was suppressed. The existing artifacts do not establish whether setup, query/history, or cleanup failed. This diagnostic does not change that result or assume that a subsequent pass fixes its cause.

Prepared artifacts are `c1_m07_transport_frames.py` and `run-transport-diagnostic-m05.sh`. Neither the plugin nor wrapper has been executed. No service, API, container, source, test, or configuration change occurred during preparation; the existing manifest checker confirmed all 345 frozen implementation inputs unchanged.

The plugin uses a `tryfirst` `pytest_runtest_makereport` hook to inspect the live exception before the default report applies traceback formatting. It handles M05 exceptions from setup, call, and teardown. Recorded fields are test node ID, phase, exception class/chain relationship, and traceback filename/function/line number. Workspace filenames are relative; filenames outside the workspace are reduced to their basename. Cause, context (including suppressed context), and exception-group members are deduplicated and bounded, with explicit truncation flags.

For HTTPX RequestError only, request metadata is restricted to an allowlisted HTTP method and a fixed backend label when the host is loopback and the port is one of 16363/18080/18090/18000. No URL, URL path/query, headers, bodies, error messages, exception repr, source snippets, frame locals, or arguments are recorded. Unknown destinations are omitted. The hook does not monkeypatch production or client methods, adjust timeouts, catch test failures, or retry requests. Successful cases and intentional skips/xfails emit no frame records. Session-start/finish markers establish plugin initialization/completion without sensitive frames.

The JSONL destination `transport-diagnostic-m05-frames.jsonl` is exclusively created with mode 0600 before test setup. Each record is flushed and fsynced. Writing failure fails the diagnostic rather than silently omitting evidence.

The wrapper lists the directory test first and then the other eleven M05 cases exactly once, including the already-passing backend-fetch case. A static AST/name check confirmed 12 unique targets matching all current M05 test functions. The command keeps the corrected gate's `-q -x`, line traceback, suppressed capture, diagnostics plugin, no cache, six provider keys unset, and offline UV settings, adding only the frame plugin on a docs-only PYTHONPATH. Fail-fast may leave later cases NOT_RUN if the first case fails again. No assertions or timeout values are weakened.

New exclusive evidence names are `transport-diagnostic-m05.log`, `transport-diagnostic-m05-junit.xml`, `transport-diagnostic-m05-exit.txt`, and `transport-diagnostic-m05-frames.jsonl`. The wrapper refuses existing paths and dangling symlinks. Its exit trap independently records pytest, tee, and script statuses. No earlier evidence is backed up, overwritten, or restored because this isolated M05 selection does not generate M01 inventory or the M03 process API log.

After root review, the proposed execution command is:

```text
bash docs/evidence/M07/run-transport-diagnostic-m05.sh
```

Static commands executed, each exit 0:

```text
bash -n docs/evidence/M07/run-transport-diagnostic-m05.sh
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python -m py_compile docs/evidence/M07/c1_m07_transport_frames.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff check docs/evidence/M07/c1_m07_transport_frames.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff format --check docs/evidence/M07/c1_m07_transport_frames.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked mypy --strict docs/evidence/M07/c1_m07_transport_frames.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python docs/evidence/M07/verify-manifest.py
```

The AST-only target check read the wrapper and parsed `tests/integration/m05/test_*.py` without importing or collecting tests; exit 0. No-index whitespace checks returned the expected new-file-difference status with no diagnostics.

Final SHA-256 values:

```text
bdc41e16749d7fc80d7c97d2a2b9a835461051e3b187f19f7d6f2d65e42bedcd  c1_m07_transport_frames.py
5c32d0b538619ae6f421f353c6949e82b36166482145dad04ee803657ea82f28  run-transport-diagnostic-m05.sh
```

At the time of this preparation, plugin loading, runtime frame capture, and the 12-case diagnostic had not executed. The later execution result is recorded below; it establishes a separate observed run, not an explanation of the original disconnect.

## Execution result

The reviewed wrapper was later executed. `transport-diagnostic-m05-exit.txt`
records pytest, tee, and script exit 0. The log and JUnit show 12 passed, one
RDFLib deprecation warning, in 2,011.05 s. The case-check JSON confirms all 12
unique expected test names were executed exactly once with no non-pass cases.
The JSONL contains only session start/finish markers because the tests passed;
it captured no failure frames. The post-diagnostic manifest check reports all
345 frozen implementation inputs unchanged. This diagnostic outcome does not
explain the original combined-gate disconnect or replace its failed result.
