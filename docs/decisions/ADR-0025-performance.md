# ADR-0025 — Performance hardening without weaker authorization

Status: accepted (M14a, 2026-10-05). The owner approved the authorization-path changes explicitly ("Approve, with ADR + tests").

## Context

The M13 bench and the M14 benchmark on makako measured about 8 s for every simple read, 23.5 s for a 64 KiB context, and 1,359 s to apply 36 replace operations. Request cost did not depend on the result size. The analysis is in [M14a](../milestones/M14a.md). The costs were round-trip multipliers:
- one content query per declared class per 200 IDs;
- one OpenFGA Check per candidate, run twice per request;
- one sequential GET per declared class for every `get_record`, repeated in every permission pass;
- context renders for every possible prefix.

AGENTS.md §5.2–5.3, ADR-0013 and ADR-0020 forbid positive authorization caches without a verified invalidation strategy, and require fresh current-binding decisions on every request.

## Decisions

1. **Round-trip counters (diagnostics only).** A context variable counts TerminusDB and OpenFGA requests per HTTP request. The boundary middleware writes them to a `c1.metrics` log line with the path, status and latency. The counts never influence a decision.

2. **Content cache keyed by an immutable commit.** `_fetch_records_content` caches decoded records, and their absence, by `(commit, installed profiles, ID, class hint)` in a bounded LRU (20,000 entries) per `Terminus` instance.
   - This is safe because a commit's content never changes.
   - Callers pass only IDs they have already authorized, and authorization stays fresh. The cache never answers "may this principal read it?".
   - `NodeRecord` is frozen, and no code mutates its lists or dicts in place (checked).

3. **Complete class hints from the journal.** The head-keyed `CurrentBindingIndex` derives, for every journaled resource, every class it was ever written with.
   - Every instance write is journaled: applied `changeset_apply` operations, and the `provision`/`probe_revision` operations, carry full records.
   - Reads probe only those classes. The cross-class duplicate check therefore stays exact.
   - Untracked IDs keep all-class probes.

4. **Batched record reads for writes.** `Terminus.get_record` goes through `fetch_records`: the same fresh profile authority and the same duplicate-identity check, but concurrent per-class queries and the content cache. Each permission pass loads every replace target once, in `_DecisionMemo.load_records`, discarded after the step.

5. **Context budget early exit.** In `build_page`, a longer prefix always renders more bytes, so the loop stops at the first overflow. The outputs equal the M13 implementation, which tests keep as data and compare against.

6. **Derived read decisions** (`AuthorizedSelection._authorize`). The pinned model defines `resource#can_read` as exactly `reader from bound_to`, and `scope#reader` as directly assigned (users and group members). Therefore `can_read(user, r)` holds if and only if a live `bound_to` scope of `r` has `user` as a reader.
   - **The rule.** C1 already requires the live `bound_to` tuples to equal exactly the journal scope (M09a D4). The decision is therefore "that scope is in the principal's readable scopes".
   - **Fresh inputs.** Both inputs come from fresh higher-consistency reads on every call: `ListObjects(user, reader, scope)` and the binding source. `finalize` repeats both, so revocation during a request is still seen.
   - **Guard.** `read_relation_is_derivable` checks the deployed model's shape when C1 starts and in readiness. It accepts the snake_case of the packaged file and the camelCase that the API serves. Readiness fails closed on any other shape, and the planner then falls back to one Check per resource.
   - **Tests.** A test pins the packaged model. Another proves equality with per-resource Checks over randomized worlds, including missing, diverged and extra bindings, group membership and mid-request revocation.

7. **Batched write-path decisions** (M09a D3, which was recorded but never wired). Each permission pass pre-decides its replace targets, part documents and references with one fresh `check_many(..., batch=True)` per principal and relation. The results seed the step's `_DecisionMemo` under the single-check keys. `check_many` gives every resource the same decision as its single check (M09a T01). The external-reference check in planning is one batched pass.

8. **Batched publication.** `_reconcile` reads live `bound_to` tuples for all new bindings from one exact source (`bound_to_many`), writes the missing tuples in atomic batches of at most 100, and confirms with a second exact read. It used to make four sequential calls per binding. Recovery reruns the same code: correct tuples are skipped, conflicts still raise 503.

9. **Receipt scan skip.** A fresh apply skips the full commit-log scan while the knowledge head still equals the base revision. The branch history is linear and a receipt can only descend from the base, so none can be reachable.

10. **Concurrent marker reads** in `detect_installed_registry` (readiness and startup), bounded at 8.

11. **Storage maintenance.** `c1-admin maintenance optimize` runs TerminusDB optimize on the knowledge and workflow databases. It is safe while C1 serves; heads and content are unchanged.

12. **Measured and dropped.**
   - Memoizing the profile-authority check would save about 3 ms per call (measured), so M07's fresh-read guarantee is kept.
   - Updating the journal snapshot in place after a write was not done. TerminusDB lists documents in layer order, not ID order, so a patched snapshot could not reproduce a fresh listing exactly, and a full listing costs about 0.2 s at 1,160 workflow documents.

## Evidence (laptop, M14 corpus S, 854 readable resources)

| Request | Before | After |
|---|---|---|
| Simple read | 2.4 s; 57 OpenFGA, 100 TerminusDB calls | 0.23 s; 24 OpenFGA, 10 TerminusDB calls |
| `graph-context` 64 KiB | 2.6 s | 0.4 s |
| 36-replace ChangeSet | 552 s | 12 s |
| 97-create ChangeSet | 61 s | 24 s |
| `/v1/instance` | 1.5 s | 0.9 s |

Makako numbers are in the M14a report.

## Consequences

- A cold content cache, after any write, costs about ⌈N/200⌉ queries per class present. A warm read at an unchanged head makes no content queries.
- Derived read decisions depend on the model shape. Changing `can_read` or `scope#reader` disables them, and readiness fails until the guard and its tests are updated deliberately.
- The cache is per process and bounded; it adds about 60 MB at its bound.
