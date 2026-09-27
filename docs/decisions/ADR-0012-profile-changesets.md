# ADR-0012 — Profile installation through ChangeSets

**Status:** M04 implementation decision under the owner's implementation request.

## Decision

A schema-bearing ChangeSet contains only `install_profile` operations from the
trusted, packaged profile catalog. The author, reviewer, and executor each
need current `schema_admin` authority. Validation compares the candidate with
the installed registry. An incompatible change is refused with `C1-PR-004` and
a workflow `MigrationProposal` describing the failed comparison; that proposal
does not execute a migration or change knowledge.

TerminusDB requires separate schema and instance-graph commits. For an
additive profile, apply first records a pending journal operation, writes the
schema, and then writes the installed-profile marker. Between those commits,
the M02 installed-profile guard rejects content access and readiness fails.
Recovery detects the packaged schema and completes the marker, then confirms
the resulting registry before it closes the pending operation. Content using
the new class goes through a subsequent reviewed ChangeSet based on the new
knowledge head. Unknown or partially matching installed schema fails closed.

## Evidence and limits

- M02-T07 and the M02 report establish the two-commit installation and
  marker guard against the pinned TerminusDB server.
- M04-T07 checks authorization, the marker interval, restart recovery,
  incompatible migration refusal, and later content creation. The M04 report
  records exact commands and results.

There is no executable migration framework in M04. A migration requires an
explicit future decision and gate. The guard is a publication boundary within
the C1 service; direct database access outside C1 is outside its promise.
