# ADR-0014 — Reviewed identity resolution and reassignment

**Status:** M05 implementation decision under the owner's implementation request.

## Decision

Identity resolution is an explicit ChangeSet operation, never a side effect of
matching names. Resolve, merge, split, and undo plans expand during validation
into exact ordinary create and replace operations. The validation report
records that expansion and the approved digest binds it. Apply repeats the
base-revision, permission, and payload checks before committing all knowledge
records and its durable receipt under the M04 writer.

A merge retains the survivor's canonical ID and marks the merged entity
superseded. A separately authorizable Redirect records the source, survivor,
and resolution decision. Every assertion about the merged identity receives
an explicit move, keep, or retract choice; omitted assignments fail with
`C1-CS-040`. Moving an assertion changes its subject while retaining the
assertion's stable ID and current security binding. Split and undo create
compensating records and changes, retaining prior history.

The M05 implementation requires the source and survivor entities, resolution,
and redirect to share one current scope. This conservative rule gives a
provable audience for the decision without inventing an ordering among
arbitrary AccessScopes. Assertions may have other scopes; their bindings never
follow an entity merge. Cross-scope entity merges require a later explicit
audience comparison and declassification decision.

## Security and evidence

Every referenced entity and assertion must be visible and editable to the
author under current authority before the plan can be complete. The service
may inspect an internal assertion inventory to reject incomplete plans, but
must never enumerate inaccessible candidates or reveal their identities in
diagnostics. Review requires the M04 independent reviewer permission. A
redirect is returned only when its own record and both identities are
readable; denied and nonexistent identities have the same 404 response.

M05-T04 exercises an incomplete merge, exact expansion, unchanged assertion
binding, merge, and compensating undo against the pinned TerminusDB and
OpenFGA stack. The M05 report records final commands, results, and any
remaining limitations after the gate.
