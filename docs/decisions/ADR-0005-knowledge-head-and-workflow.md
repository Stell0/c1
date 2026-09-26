# ADR-0005 — Knowledge head, receipt, and publication journal

**Status:** accepted within the owner's M01 implementation request, 2026-09-26.

## Context and decision

A ChangeSet's workflow bookkeeping must not advance the knowledge revision it
proposes to update. The reference deployment assigns knowledge to `c1` and
workflow records to `c1_workflow`, two databases on the **same TerminusDB
server**. This is not a second knowledge store. M01 creates per-test equivalents
named `c1_m01_<id>` and `c1_m01_<id>_workflow`; it has not deployed the final
product databases or ChangeSet lifecycle.

For an M01 knowledge insert, `ProbeWriter` puts a JSON receipt in the **knowledge
commit message**: version marker, ChangeSet ID, synthetic probe principal,
repository/database name, and SHA-256 of the canonicalized request payload. The
knowledge commit is the durable evidence of the write. A `Receipt` document in
the workflow database is a later projection, never a condition for treating the
knowledge commit as durable. `find()` scans the knowledge log for the matching
ChangeSet, principal, repository, and digest; a reused key with a different
digest is rejected, and multiple matching commits are an error. The projection
can be recreated after a lost acknowledgement without writing knowledge again.

An `asyncio.Lock` keyed by knowledge database serializes writers within one
process. Every knowledge write also sends the expected branch head, so a stale
writer fails at TerminusDB. This does not establish serialization among arbitrary
processes or hosts; M02 must decide and prove the product writer's coordination.
Workflow writes have their own head and do not make a knowledge proposal stale.

## Evidence for the receipt boundary

On 2026-09-26, the real-stack T02–T04 command recorded in
[ADR-0004](ADR-0004-terminusdb-access.md) passed all three tests. T02 showed a
schema-invalid batch produced neither knowledge documents nor a knowledge
commit; a valid batch produced one knowledge commit with the receipt metadata,
then a workflow projection. T03 showed stale-base rejection, a commit whose
acknowledgement was deliberately discarded before projection, recovery from
the knowledge log, and a retry that created no second knowledge commit. It also
tested distinct principals and a log longer than common default page lengths.
T04 showed that old document versions remain readable. These tests do not prove
all future ChangeSet operations, repository-wide multi-process serialization,
or a transaction spanning the two databases.

## Publication and historical-read boundary

`probes/publication.py` implements a separate M01 experiment. A workflow
`Publication` journal records the resource, requested scope, payload, base
revision, knowledge commit, and a state in `pending`, `content_written`,
`binding_written`, `complete`, or `failed`. The publisher writes `pending` before
content, then commits content, updates the current OpenFGA binding, confirms that
binding and the committed content, and finally writes `complete`. Crash injection
is available after the journal, content, and binding steps. A non-complete or
missing journal blocks the reader. On a handled failure the implementation marks
the journal `failed` and attempts to remove current binding tuples; **the failed journal is
the deny tombstone**. The prototype OpenFGA model has no deny relation or deny
tuple. Transport or OpenFGA outages leave a non-complete state for retry.

For every read, including an old knowledge commit, `Publisher.read()` first
checks the **current** journal state, confirms the **current** resource-to-scope
binding equals the journal scope, and asks OpenFGA for a fresh `reader` decision
before retrieving content. Missing or untrusted workflow, binding, or FGA state
returns no content. `probes/fga.py` requests `HIGHER_CONSISTENCY` for checks and
binding reads; [OpenFGA's consistency documentation](https://openfga.dev/docs/interacting/consistency)
says this bypasses enabled caches. The reader also uses a local file lock shared
with publication on this host. None of this makes TerminusDB and OpenFGA one
distributed transaction, recalls already delivered bytes, or proves safety under
all concurrent policy changes. T05 and T06 must supply the live freshness,
crash/restart, service-outage, and latency results; this ADR does not record
those checks as passing. M03 must specify the product authorization model and durable
publication/re-scope coordination from that evidence.

## Sources and limits

The [TerminusDB commit-message guide](https://terminusdb.org/docs/commit-message-howto/)
and [document API reference](https://terminusdb.org/docs/document-insertion/)
support commit metadata and version reads. The pinned upstream
[data-version tests at v12.0.7](https://github.com/terminusdb/terminusdb/blob/v12.0.7/tests/test/data-version.js)
provide version-specific behavior used in the M01 plan. The M01 implementation
and T02–T04 tests provide the local evidence above. The workflow database stores
bookkeeping, not a copy of the graph; no schema-plus-instance single-request
transaction was tested. Any move to a PostgreSQL journal would be a separate
architecture decision requiring owner approval.
