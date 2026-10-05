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

7. **Storage maintenance.** `c1-admin maintenance optimize` runs TerminusDB optimize on the knowledge and workflow databases. It is safe while C1 serves; heads and content are unchanged.

8. **Measured and dropped.** Memoizing the profile-authority check would save about 3 ms per call (measured), so M07's fresh-read guarantee is kept.

## Evidence (laptop, M14 corpus S, 854 readable resources)

| Request | Before | After |
|---|---|---|
| Simple read | 2.4 s; 57 OpenFGA, 100 TerminusDB calls | 0.23 s; 24 OpenFGA, 10 TerminusDB calls |
| `graph-context` 64 KiB | 2.6 s | 0.4 s |
| 36-replace ChangeSet | 552 s | 123 s (before the write-path batching) |

Makako numbers are in the M14a report.

## Consequences

- A cold content cache, after any write, costs about ⌈N/200⌉ queries per class present. A warm read at an unchanged head makes no content queries.
- Derived read decisions depend on the model shape. Changing `can_read` or `scope#reader` disables them, and readiness fails until the guard and its tests are updated deliberately.
- The cache is per process and bounded; it adds about 60 MB at its bound.
