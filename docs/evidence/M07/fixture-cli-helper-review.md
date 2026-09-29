# Fixture CLI evidence helper — prepared, not executed

Status: static preparation complete; lead and advisor review and subsequent execution remain pending. This helper was not invoked, and no service, API, container, fixture loader, or full check was run during preparation. Production, test, and configuration inputs to the running 79-case gate were not changed.

The earlier `fixture-load-final.log` ends with the synthetic loader JSON indicating `fixture: cross-project-batteries` and `state: applied`. Its original process exit was not captured and remains **NOT_OBSERVED**. This new helper captures a distinct execution of the existing CLI; it does not reconstruct or backfill that earlier exit.

## Scope and execution boundary

`run-fixture-cli-gate.py` reuses `tests.integration.m03.conftest.live_case()`. The factory allocates UUID-suffixed knowledge/workflow databases, a fresh OpenFGA store/model, a separate `m03_<uuid>` instance ID, and a unique absolute writer lock path. The fixture requires `urn:c1:instance:dev:` for its synthetic resource IRIs; that shared IRI namespace does not share databases, authorization stores, instance grants, or writer locks.

Before resource allocation, the helper:

- Refuses any existing destination artifact, including dangling symlinks. Every destination is then reserved using `O_CREAT | O_EXCL` with mode `0600` before entering the factory.
- Requires the future post-transport ordered gate's `post-transport-live-exit.txt` to report `pytest_exit=0`, `tee_exit=0`, `restore_exit=0`, and `script_exit=0`. `post-transport-live-junit.xml` must have exactly 79 actual testcases and 79 unique `(classname, name)` identities, with the suite count also totaling 79, no failures/errors/skips in suite totals, and no failure/error/skipped testcase children. The derived node identities must also equal the 79 unique entries in `corrected-live-expected-cases.json`. Neither earlier failed gate can satisfy this prerequisite.
- Checks that trusted `probes.config.environment()` cannot restore removed provider variables, `C1_API_URL`, or crash flags. The loader rereads `.env` and uses `setdefault`, so inherited-variable removal alone would be insufficient.

The parent closes `case.runtime` and asserts `case.runtime.operations.writer.fd is None` before spawning the child. Runtime shutdown closes its own clients; the outer factory's separate FGA, Journal, and Terminus clients remain open for cleanup. The later lifespan shutdown closes Runtime again. Inspection of the pinned HTTPX 0.28.1 `AsyncClient.aclose()` confirms that a closed client is not closed again; `WriterGate.close()` similarly checks `fd is not None` before closing. No parent API calls occur after Runtime is closed.

## Existing CLI and environment

The child uses Unix `asyncio.create_subprocess_exec(..., start_new_session=True)` without a shell and with stdin disconnected. Its PID is the only owned process-group ID. Its exact argument list is recorded in the result JSON:

```text
uv run --locked python scripts/load_fixture.py --fixture cross-project-batteries --database c1_m03_k_<factory uuid>
```

The environment starts with the process environment plus trusted local credentials. All `Settings.from_env()` deployment fields are explicitly populated from `case.settings`: instance ID/base, issuer/alias/audience, FGA URL/token/store/model, Terminus URL/password/organization/databases, writer lock path, independent review, cursor secret, and query limits. Probe routes are explicitly disabled for this ordinary-API loader. `C1_CRASH_AFTER`, `C1_PROBE_CRASH_AFTER`, and `C1_API_URL` are removed; trusted local configuration containing any of those keys is rejected before allocation. Six provider-key variables are likewise removed and forbidden in the trusted file. UV is offline and uses repository-local cache/Python directories. No credentials, tokens, headers, environment mapping, or response bodies are printed by the helper.

No CLI flags, loader behavior, production source, tests, or deployment configuration were added or changed. The child hosts the existing application in-process with the factory's security and storage resources; it does not connect to an already-running development API or use development databases.

## Evidence and cleanup semantics

New exclusive destinations are:

- `fixture-cli-stdout.log`: child stdout, including only existing CLI output and synthetic audit/result records.
- `fixture-cli-stderr.log`: child stderr for the actual CLI execution.
- `fixture-cli-result.json`: exact argv, generated instance/database names and FGA store/model IDs, actual child return code, final-JSON validation, wrapper outcome, cleanup outcome, and safe failure phase/type metadata. Backend credentials are excluded; retained-resource identifiers support a later explicitly controlled cleanup.
- `fixture-cli-exit.txt`: the actual child return code, followed by cleanup status and wrapper return code. Child completion is flushed and fsynced before factory cleanup; remaining artifacts are flushed and fsynced before return.

The helper validates only the last nonempty stdout line for the fixture name and `state: applied`. This is additional evidence, not a substitute for `child_returncode == 0`. Child exit, wrapper failure, and factory cleanup status remain independent fields; a wrapper or cleanup failure never rewrites the child's observed exit. Safe error summaries include phase and exception class, not exception messages or tracebacks.

A cancelled spawn remains owned through a shielded task until its process handle is obtained. Cleanup sends SIGTERM only to the new session's owned process group, so uv's possible Python subprocess is included. It polls group absence for at most eight seconds, sends SIGKILL to that same group if it persists, then requires group absence within a further two seconds. It makes a bounded two-second attempt to reap the direct child even when group verification fails. Successful cleanup additionally requires a final `killpg(pgid, 0)` check to raise `ProcessLookupError`, establishing that the owned group is absent after the direct child is reaped. Signal errors, a remaining group, or an unsuccessful reap are uncertainty, never a successful proof. No global process searches or signals to other groups occur. The helper translates its own SIGTERM into task cancellation; the cleanup task remains shielded against additional cancellation and its result is retrieved.

The focused reviewer recommended this conservative kernel-group absence test over accepting a `/proc` process leader in state Z: a zombie thread-group leader alone does not prove other threads have stopped. A persistent group, including one containing only zombies, is therefore retained as unproven rather than interpreted as safe for deletion. This can retain resources unnecessarily, but it avoids deleting storage under an active loader.

The result records the owned PGID and `child_cleanup_status` independently from the actual child exit and factory cleanup outcome. On any spawn-handle or cleanup-proof uncertainty, the helper records `child_cleanup_status=FAIL_OR_UNKNOWN`, `cleanup_status=NOT_RUN_RETAINED`, the available child return code, generated database/store IDs, and a safe failure phase/type. It flushes and fsyncs the available child output, result JSON, and exit evidence, then deliberately calls `os._exit(1)` **inside the factory body**. This bypasses the factory's database/store deletion finalizers; raising or returning would incorrectly run them. Evidence persistence errors receive a safe exception-type diagnostic; the hard exit still retains resources. No retention path attempts backend deletion.

Only proven child/group cleanup permits exiting `live_case()`, which drops its generated workflow database, knowledge database, and FGA store. The existing factory may leave its inert UUID lock file, but the parent fd is closed and the child/group proof has passed. This helper does not delete unrelated filesystem state. Factory cleanup errors are recorded as `FAIL_OR_INCOMPLETE`, never as PASS. Retained resources require a later explicit cleanup using the recorded UUID database and store identifiers after independently resolving process uncertainty; no automatic retry or cleanup is promised.

## Static checks executed

Each final command exited 0:

```text
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python -m py_compile docs/evidence/M07/run-fixture-cli-gate.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff check docs/evidence/M07/run-fixture-cli-gate.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked ruff format --check docs/evidence/M07/run-fixture-cli-gate.py
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked mypy --strict docs/evidence/M07/run-fixture-cli-gate.py
```

An initial Ruff check found `UP047` on the generic cleanup function. It was changed to the Python 3.13 type-parameter syntax; the subsequent scoped check passed. Formatting was applied only to the helper. These static checks neither import nor invoke its execution entrypoint. No mirror unit tests were added for this evidence-only wrapper.

After the final conservative absence proof and durable hard-exit retention changes, all four commands above were rerun and exited 0. The cleanup-reviewed helper's earlier SHA-256 from `sha256sum docs/evidence/M07/run-fixture-cli-gate.py` is:

```text
db8c43c9b0f8d2a41e20da9e92f9750d4a89bebb197b5f3ede6530d392330d0e
```

## Reproduction after review and gate completion

Run from the repository root only after the lead and advisor approve the concrete helper and the post-transport ordered gate has successful terminal evidence:

```text
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python docs/evidence/M07/run-fixture-cli-gate.py
```

The wrapper obtains private settings internally; do not put them in a shell command or evidence document. Existing artifacts intentionally prevent a second execution under the same evidence names. Do not delete or overwrite captured evidence to force a rerun.

Remaining uncertainties: this helper has not executed its subprocess, cancellation, or live cleanup paths; static checks cannot establish those guarantees. The future result must demonstrate the actual CLI return code and cleanup outcome. Lead/advisor review must assess the helper before execution, and resulting child logs must be checked for confidential material before publication. No milestone gate is claimed by this preparation document.

The lead and Astra advisor reviewed the final helper digest above on
2026-09-28. The advisor confirmed that the cleanup blockers were resolved:
uncertainty retains the isolated resources, while normal deletion requires
bounded direct-child reaping and kernel-confirmed group absence. No remaining
source-review blocker was found. Execution still requires successful terminal
post-transport gate evidence and the lead's verification of its expected cases.
Neither reviewer executed subprocess, cancellation, or live cleanup paths.


## Post-transport prerequisite preparation

Only the prerequisite evidence filenames, exact expected-node validation, and recorded prerequisite label were changed after the cleanup review. The future `post-transport-live-exit.txt` / JUnit must pass both counts and exact identity equality with `corrected-live-expected-cases.json`. Environment fields, credential handling, child spawning, process-group cleanup, and retention behavior are unchanged. The four scoped static commands above were rerun and all exited 0. Current helper SHA-256:

```text
7ddca5171653b5f9adb05f9ae41297706a93d8320da5f4c5ac8a0280956c7d84
```

These prerequisite changes await the lead's review; the earlier advisor cleanup review applies to the earlier digest, not an execution of this new digest. No helper execution occurred.
