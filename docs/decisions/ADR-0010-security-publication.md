# ADR-0010 — Durable security publication and recovery

**Status:** M03 implementation decision under the owner's implementation request.

## Decision

One process owns a lifetime advisory file lock; a coroutine lock serializes its
security writes. A second process cannot acquire writer ownership. Reads remain
lock-free and use the current-state gates in ADR-0009. This is a single-host,
single-writer boundary, not a distributed transaction.

The separate TerminusDB workflow database stores typed envelopes for Scope,
Binding and Operation records. Atomic CAS updates save pending intent together
with every affected non-active Binding, and later save activation together with
the applied operation. Payload JSON is operational recovery state, not a second
knowledge graph. The configured core knowledge schema remains authoritative.

Provisioning records intent before content, writes the exact validated canonical
record, assigns the FGA binding, confirms both, then activates publication.
Recovery compares existing content before continuing. Probe revision recovery
requires the current unique binding and contributor authority before writing.
Content confirmation compares exact RDF term sets, including literal lexical
text, datatype and language; backend Set ordering is not part of the record's
meaning. It does not normalize away a different lexical value or missing term.
Probe routes accept synthetic identities only and are disabled by default;
general ChangeSets, atomic knowledge receipts and public CRUD remain M04 work.

Every rescope is treated as possible declassification because scopes have no
total audience ordering. Actor and executor need source and destination
administration; approval requires destination administration and, by default, a
different principal. Apply rejects a changed reviewed target set. Pending
transitions deny reads at head and historical commits. Recovery rechecks actor
and approver authority before changing or publishing state.

An already-completed revocation can be confirmed without restoring the actor's
now-revoked authority: recovery reads the exact tuple and only closes the journal
if it is absent. This introduces no grant and permits self-revocation to recover
after a crash. Other lost-authority recovery stays pending, denies affected
resources, and leaves readiness false; it is not reported as successful.

Startup recovery and operator-triggered retry reconcile pending operations.
Proposed and approved operations have not changed publication and do not block
readiness. Fault injection exits the process after journal, tuple or confirmation
only when synthetic probe routes are enabled. Structured audit output contains
principal/target IDs, operation, correlation ID, outcome and reason, never record
bodies or tokens.

## Evidence and sources

- [TerminusDB versioned JSON](https://terminusdb.org/docs/version-controlled-json/)
  and [schema CRUD](https://terminusdb.org/docs/schema-crud-operations/) inform
  commit reads and atomic document replacement; pinned live tests establish the
  actual behavior relied on here.
- `test_journal_contract.py` proves mixed create/update in one commit, stale CAS
  and invalid-batch rollback, and historical knowledge reads.
- M03-T06 kills a real API process at all three publication boundaries, restarts
  under an unavailable OpenFGA, and verifies denial before successful recovery.
- M03-T07 checks real service outages. Unit recovery regressions cover the
  already-absent revocation and current-binding requirements above.

An undecidable operation requires operational repair and remains fail closed.
Multi-host locking, service replication, production deployment and general
knowledge transaction receipts are not claimed by this milestone.
