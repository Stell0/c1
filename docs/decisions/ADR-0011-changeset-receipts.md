# ADR-0011 — Reviewed ChangeSets, receipts, and retries

**Status:** M04 implementation decision under the owner's implementation request.

## Decision

An ordinary knowledge write is a ChangeSet in the workflow journal. Its draft,
submission, validation report, independent approval, and application are
separate journal transitions. Editing or rebasing increments the attempt and
invalidates the previous report and review. Validation mints omitted resource
identifiers before review and stores the normalized payload and its canonical
JSON digest. Apply recomputes that digest, checks the knowledge head and current
authority for every target and referenced resource, then uses one TerminusDB
instance-graph `PUT create=true` for the whole content batch and its
per-scope provenance activities. No ordinary CRUD endpoint bypasses this path.

The commit message carries receipt version 2: ChangeSet ID, attempt, principal,
repository, and approved digest. The workflow journal first marks all affected
bindings pending, so reads fail closed across the backend and OpenFGA boundary.
After a commit, the service confirms content and tuples before activating
bindings and marking the ChangeSet applied. Startup and explicit recovery scan
every reachable page of the knowledge log for an exact receipt before deciding
to write. A recovered receipt is authoritative even if the original HTTP
response or journal update was lost. An unresolved operation stays pending and
readiness fails closed.

Create and apply requests require a printable, bounded idempotency key. The
journal address binds principal, repository, and key to the request digest;
same key and digest replays the stored result, while a changed digest is an
error. Receipt matching additionally checks the ChangeSet attempt and
approved digest. The knowledge head alone decides staleness; workflow writes
cannot stale a proposal. Historical content and history cursors recheck the
current resource binding and grants on every request.

An assertion without source evidence may be accepted only as an explicitly
attributed manual statement. Competing claims remain independent records; a
known overlap of claims for a declared single-valued predicate is an
informational validation flag and does not erase either claim. A restore is a
new reviewed replacement whose payload must equal the selected historical
record; it never restores old security bindings.

## Evidence and limits

- M01-T03 and ADR-0005 established commit-message receipts and idempotent
  retries on the pinned TerminusDB server. M03-T06 and ADR-0010 established
  pending-binding denial and crash recovery across OpenFGA.
- M04-T01–T06 exercise the product route and real pinned services, including
  log paging past one page, crash points after journal/commit/tuple/confirmation,
  cross-scope atomicity, current-binding restore, and authorization negatives.
  Exact commands, revisions, and results are in `M04-report.md`.

This is a single-host, single-writer protocol. A permanently unavailable or
inconsistent dependency requires operator repair and remains fail closed; it
is not a distributed transaction or an exactly-once claim across arbitrary
external writers.
