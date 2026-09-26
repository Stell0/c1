# ADR-0004 — TerminusDB access for M01 probes

**Status:** accepted within the owner's M01 implementation request, 2026-09-26.

## Context and decision

M01 must test the pinned TerminusDB community image from Python 3.13. The published
`terminusdb-client` 10.2.6 package declares Python `>=3.8,<3.12`, so it cannot
serve this harness. Its PyPI license classifier also says “Other/Proprietary
License (Apache Software License)”; this metadata conflict is a review reason,
not a finding that the repository's Apache-2.0 license is unusable. Use pinned
`httpx` 0.28.1 against TerminusDB's HTTP API for the isolated probes. Basic admin
authentication is confined to the private development stack; production identity
and delegated authorization are outside M01.

`probes/terminus.py` creates and drops only database names matching `c1_m01_*`.
It inserts schema classes into `graph_type=schema` and ordinary documents into
the instance graph. It sends `author` and `message` on document writes. It reads
the returned `TerminusDB-Data-Version: branch:<commit>` header and sends that
exact token on writes with an expected head. `GET /api/document` uses
`as_list=true`, including for a single ID, so an absent ID is an empty JSON
array rather than an ambiguous streamed error body. The probe preserves the
database's default schema context: TerminusDB v12.0.7 rejected a new `@context`
through schema `POST` with HTTP 400 `api:InsertingContext`, saying a full replace
is required. Context replacement is not part of this probe.

## Observed operations and boundaries

The T02–T04 results below were exercised against the pinned local stack by
`C1_STACK=1 uv run pytest -q tests/integration/m01/test_t02_atomic.py
tests/integration/m01/test_t03_stale_and_reconcile.py
tests/integration/m01/test_t04_revisions.py -p no:cacheprovider` on 2026-09-26:
**3 passed, exit 0**. The exact service/image identity belongs in the M01 report.

| Operation | Observed result |
|---|---|
| `POST /api/db/{org}/{db}` and `DELETE /api/db/{org}/{db}` | Each test created and cleaned up its own probe database. |
| `POST /api/document` with `graph_type=schema` | Class definitions inserted using the default context. |
| Multi-document instance `POST` | A three-document batch whose third item lacked a required field failed with HTTP 4xx; head, log, and document set stayed unchanged. A valid three-document batch produced exactly one new log commit and all three documents. This is evidence for this operation and fixture, not for arbitrary mixed operations. |
| Expected-head write | A stale `TerminusDB-Data-Version` failed with HTTP 400 `api:DataVersionMismatch`; head and log stayed at the winning commit. |
| `PUT` replacement and `DELETE` documents | A second value and then deletion each advanced the head. Deletion left earlier commits readable. |
| `GET /api/document/.../local/commit/{id}` | Two selected commits returned the expected distinct values, including after current deletion. |
| `GET /api/history`, `GET /api/log`, `POST /api/diff` | History and log returned commit identifiers/messages; diff reported the tested integer field as `SwapValue` with before/after values. |

The test suite did **not** exercise schema and instance writes in one request,
context full replacement, JWT authentication, arbitrary transaction shapes,
cross-database atomicity, or product API behavior. Those remain unproven; M02
must select and test any operation it needs. The probe does not expose a backend
query escape hatch to C1 clients.

Separately, the live T07 setup initially submitted a custom `@context` through
schema `POST` and received HTTP 400 `api:InsertingContext`. The M01 schemas now
retain the database's default context. A full-context replacement was not tested.

## Sources and consequences

The [TerminusDB document API reference](https://terminusdb.org/docs/document-insertion/)
describes the version header and commit path; its
[commit-message guide](https://terminusdb.org/docs/commit-message-howto/)
specifies `author` and `message` on document writes. The
[HTTP API reference](https://terminusdb.org/docs/openapi/) lists database,
document, log, history, and diff endpoints. Version-specific source and tests
consulted for the M01 plan are
[data-version.js at v12.0.7](https://github.com/terminusdb/terminusdb/blob/v12.0.7/tests/test/data-version.js),
[document.js at v12.0.7](https://github.com/terminusdb/terminusdb/blob/v12.0.7/tests/test/document.js),
and [history.js at v12.0.7](https://github.com/terminusdb/terminusdb/blob/v12.0.7/tests/test/history.js).
The [PyPI metadata for terminusdb-client 10.2.6](https://pypi.org/project/terminusdb-client/10.2.6/)
states its Python constraint and classifier. The live test results above establish
only the pinned stack behavior actually asserted by T02–T04.
