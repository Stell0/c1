# ADR-0026 — Performance hardening, part 2

Status: accepted (M14b, 2026-10-06). The owner approved the plan and OD1–OD4 ("I approve all of 4 optional improvements").

## Context

After M14a (ADR-0025), a simple read on makako took about 2.4 s; the same request takes about 0.23 s on the laptop. Per-phase timing (decision 1) shows that on the laptop:
- the read planner's two authorization passes (build, then finalize) take about 160 ms;
- content fetch takes about 50 ms.

`finalize` repeats the principal's scope enumeration (ListObjects) and the whole-store binding scan. It exists so that a revocation during the request is enforced (AGENTS.md §5.2–5.3).

## Decisions

1. **Phase timing (diagnostics only).** The per-request metrics line adds per-backend wall time (`backend_ms`) and named phase times (`phases_ms`):
   - authentication;
   - plan build, authorize and finalize;
   - binding source;
   - content fetch and schema authority;
   - journal view and save;
   - context select, units and render;
   - apply stages.

   Times are wall-clock sums and overlap when work runs concurrently.

2. **Finalize through the OpenFGA change log (OD1).** For a verified read model (ADR-0025), a plan's decisions are a function of only:
   - the OpenFGA tuples (`bound_to`, scope readers, group members), under the fixed model;
   - the journal state at the plan's workflow head.

   The steps:
   - **Build** advances a process-wide change-log position (`GET /stores/{id}/changes`) *before* its ListObjects and binding reads, and keeps it in the plan.
   - **Finalize** reads the change log from that position. If it holds **no change at all**, fresh reads would return the same inputs, so the plan's result stands. The workflow head is still verified before and after, as before.
   - **Any change,** even an unrelated one, takes the full fresh path (ListObjects and the binding source), and so does an error reading the log, an unverified model or a missing position.

   **Assumptions, part of this decision:**
   - Every tuple write C1 makes goes through its single writer (`WriterGate`: security operations and ChangeSet publication). Writes are therefore sequential, and a committed change can never appear in the log *behind* a position that was already read. `c1-admin` writes tuples only at bootstrap, and in disaster recovery while C1 is guarded (503).
   - The deployments pin `OPENFGA_CHANGELOG_HORIZON_OFFSET=0`, so every committed change is visible immediately.
   - OpenFGA writes a tuple and its change-log entry in the same datastore transaction.

   **Tests:** `tests/unit/m14b/test_finalize_changes.py` covers:
   - an unchanged store skips the OpenFGA reads;
   - a membership revocation, a re-scope or a reader removal between build and finalize forces fresh reads and is enforced;
   - an unrelated change still forces fresh reads;
   - change-log errors fall back to the full path;
   - an unverified model never uses the shortcut.

   M14b-T02 adds integration checks against real services.

3. **Lean journal listing (OD2).** `ValidationReport`, `ReviewDecision`, `ApplyReceipt`, `Idempotency` and `MigrationProposal` entries are only ever read by ID. They move to a second document class, `WorkflowRecord`, with the same fields, digest addressing and decoding checks. A decoded envelope must sit in its kind's class.
   - The listing that every workflow step reloads (`type=WorkflowEntry`) now holds only scopes, bindings, operations, ChangeSets and restores. On the laptop probe corpus it holds 2.5 MiB of 5.4 MiB.
   - **Migration** (`Journal.migrate_records`) runs at startup, before recovery reads any entry:
     1. add the class to the schema;
     2. copy each legacy record to its new address (one commit per 500);
     3. delete the legacy copies.

     It is idempotent. A crash between the copy and the delete leaves both copies, and the next start finishes. Readers use only the new address.
   - **Startup order** is the guard against migrating while an operation is pending: C1 does not serve and runs no recovery until the migration is done. Pending operations are then recovered as before, reading their records at the new addresses.
   - **Readiness** requires both classes in the schema.
   - **Tests:** `tests/unit/m14b/test_journal_records.py`. M14b-T03 covers backup and restore on real services.

4. **History from the journal (OD4).** `/v1/history` first tries an index of the journal.
   - **Index rule:** take every applied `changeset_apply` operation whose records include the resource. Its commit is the operation's `revision`. The commit must be found in the knowledge database's current commit log, and that commit's receipt must name the ChangeSet.
   - **Fallback to the M13 per-class TerminusDB history probes** happens when:
     - a `provision` or `probe_revision` operation wrote the resource;
     - no indexed write exists (data written before journaling);
     - a receipt does not match;
     - a revision is malformed.
   - **Restores:** only commits reachable in the current log count, so a knowledge-only restore (which keeps the newer journal) drops the commits it discarded.
   - **Unchanged:** authorization, cursor, page order and suppression rules.
   - **Equivalence:** on the laptop probe corpus, 60 of 60 sampled resources had identical entries (commit, timestamp, message) in identical order. The sample took 6.9 s indexed against 401 s with backend probes (`scripts/history_equivalence.py`). A warm `/v1/history` dropped from 6.8 s to 1.1 s.
   - **Tests:** unit tests in `tests/unit/m14b/test_history_index.py`; integration in M14b-T04.

5. **One security view per apply step.** `_planned_records` and `_finish` look up bindings in a single `journal.view()` instead of one journal read per record. No write happens between those lookups, and both run under the writer lock. On the laptop, the 97-create apply dropped from 18.2 s to 7.9 s, and corpus loading from 172 s to 69 s.

## Measured (laptop, M14 corpus S, warm)

| Step | M14a | M14b so far |
|---|---|---|
| Simple read | 0.23 s, 22–24 OpenFGA calls | 0.20–0.28 s, 13 OpenFGA calls |
| `plan.finalize` | about 95 ms (ListObjects and a binding scan) | about 64 ms, which is one change-log read plus two workflow head reads (about 30 ms each, the fail-closed barrier) |
| `/v1/history` | 6.8 s | 1.1 s |
| 97-create apply / 36-replace apply | 18.2 s / 7.5 s | 7.9 s / 4.9 s |

## Consequences

- With no concurrent security change, `finalize` costs one change-log read instead of one ListObjects call and a whole-store scan.
- Under frequent security writes, `finalize` behaves as in M14a.
- More than one C1 writer process, or tuple writes from outside C1 while it serves, would break assumption 1. Such a deployment must disable the shortcut. That is a recorded constraint of the single-writer architecture (AGENTS.md §4.2).
