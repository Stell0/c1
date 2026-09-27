# M04 — Reviewed knowledge writes and history: execution report

**Gate:** VERIFIED

M04-T01–T07 and applicable M01–M03 regressions passed against the
implementation revision below, with no unresolved gate failure.

Approved plan revision: `7a19e0e` (`docs/milestones/M04.md`). Starting revision:
`c6b62fd1b2aa54b8f1abb8154f1acdf2174b5584`. Implementation revision:
`85f67d90ca45200378d58bad5859b2dc2f79eb26`. Execution date: 2026-09-27.

## Delivered behavior

Authenticated clients can create a ChangeSet against the opaque knowledge
revision returned by `GET /v1/instance`, submit and validate it, obtain an
independent review, and apply the exact approved payload. Content creates and
replacements across scopes are committed in one TerminusDB transaction with a
versioned receipt in the commit message. New resources and per-scope activities
remain unpublished until current OpenFGA bindings and committed content are
confirmed. Idempotency is keyed by principal, repository, request digest, and
request key; startup and explicit recovery search paged log history before a
retry can write again. Draft/review bookkeeping does not move the knowledge
head. Restores are reviewed new changes that retain current security bindings.

The API provides current-authority reads of canonical resources and their
history at selected knowledge revisions. Missing and unreadable references
produce the same validation code. Imported claims need evidence or an activity;
attributed manual claims are explicit. Competing claims for a declared
single-valued predicate remain separate and receive an informational flag when
their known intervals overlap. A trusted additive profile is installed through
a schema-bearing ChangeSet and a guarded marker commit. Incompatible changes
produce a refused MigrationProposal record, not an executable migration.

All ordinary client knowledge writes use ChangeSets. M03's separate security
operations and disabled-by-default synthetic probe routes remain available for
their own purposes. M04 adds no model runtime, provider account, or AI key.

## Decisions and review

[ADR-0011](../decisions/ADR-0011-changeset-receipts.md) records the workflow,
one-commit receipt, idempotency, and fail-closed recovery boundary.
[ADR-0012](../decisions/ADR-0012-profile-changesets.md) records guarded schema
publication and migration refusal. The M04 plan's decisions D1–D13 were
implemented without changing its acceptance criteria.

Review found and fixed the following issues before the gate: generated IDs had
to use the configured instance base and UUID form; review visibility needed
read checks on targets and referenced resources; a revoked approver needed a
clean whole-ChangeSet denial; conflict cardinality belongs to the subject's
class property as well as the global predicate; the pinned TerminusDB history
timestamp is numeric Unix seconds; and history requests must deny during a
half-installed schema just as resource requests do. Live and focused tests
cover these fixes. `GET /v1/instance` now exposes the opaque head to an
authenticated client, so its first ChangeSet can be created using only public
API calls; it returns 503 while the repository is unpublished.

## Runtime and checks

Python 3.13.14; pinned TerminusDB 12.0.7, OpenFGA 1.21.0, Keycloak 26.7.4,
and PostgreSQL 17-alpine. The service image digest pins and Python lock are
unchanged. Synthetic M04 fixtures use isolated disposable knowledge/workflow
databases, OpenFGA stores, and Keycloak development principals. No company
payload, bearer token, or deployment credential appears in the versioned
evidence. The only new secret-scan exception is an audited mock-transport test
value; see [secret audit](../evidence/M04/secret-audit.md).

| Named check | Executable coverage | Result |
|---|---|---|
| M04-T01 | `test_t01_reviewed_apply.py`: source-backed and manual assertions, one commit, receipt, activity | PASS |
| M04-T02 | `test_t02_invalidation.py`: edit invalidation and independent review | PASS |
| M04-T03 | `test_t03_cross_scope.py`: two-scope atomicity and revoked reviewer | PASS |
| M04-T04 | `test_t04_retry_crash.py`: replay, conflicting key, four real process crash points, paged receipt recovery | PASS |
| M04-T05 | `test_t05_revision.py`: workflow head independence, stale content base, rebase | PASS |
| M04-T06 | `test_t06_restore_security.py`: compensating restore under current binding and negative reads | PASS |
| M04-T07 | `test_t07_schema_conflict.py`: reference non-disclosure, guarded schema crash/recovery, incompatible proposal, two independently sourced competing claims | PASS |
| Supporting storage | `test_storage_paging.py`: pinned backend paging/history | PASS |

The full M04-only live group passed 14 tests in 579.79 seconds, with no skips.
The pinned log endpoint returned three distinct four-entry pages for twelve
commits. In the crash recovery case, 25 unrelated commits put the ChangeSet
receipt beyond the first 20-entry page; the test proves its absence on page
one, presence on page two, and exactly one final receipt after recovery.
The strengthened T07 schema-crash test, which also checks historical metadata
denial, passed again on the pinned stack (1 test, 33.08 seconds). The
[reviewed-write demo](../evidence/M04/demo-verify.md) applied one ChangeSet in
one commit, checked its receipt, and returned authorized history; its first
attempt exposed the numeric timestamp mismatch and is recorded in
[demo-attempt.md](../evidence/M04/demo-attempt.md). The corrected run exited 0.
A [wheel build check](../evidence/M04/wheel-check.md) confirms both trusted
profile catalogs are packaged.

Focused commands run before the aggregate gate were
`C1_STACK=1 UV_CACHE_DIR=/tmp/uv-c1-m04 uv run --locked pytest -q -x --tb=short --show-capture=no tests/integration/m04 -p no:cacheprovider`
(14 passed),
`C1_STACK=1 UV_CACHE_DIR=.uv-cache uv run --locked pytest -q -x --tb=short tests/integration/m04/test_t07_schema_conflict.py::test_t07_schema_commit_crash_blocks_reads_until_recovery -p no:cacheprovider`
(1 passed), and the equivalent T04 command selecting
`test_t04_crash_recovery_has_one_receipt[commit]` (1 passed). Each exited 0
against the pinned live services. The final 53-test aggregate gate ran after
both fixes.

| Exact command | Exit | Result/evidence |
|---|---|---|
| `make bootstrap` | 0 | PASS; [log](../evidence/M04/bootstrap.log) |
| `make check` (with loopback-capable sandbox) | 0 | PASS; [log](../evidence/M04/check-final.log) |
| `make stack-up` | 0 | PASS; [log](../evidence/M04/stack-up.log) |
| `C1_STACK=1 make integration` | 0 | PASS; 53 live tests, no skips or failures; [log](../evidence/M04/integration.log), [JUnit](../evidence/M04/integration-junit.xml) |
| `C1_STACK=1 make probe` | 0 | PASS; 12 M01 live tests; [log](../evidence/M04/probe.log), [JUnit](../evidence/M04/probe-junit.xml) |
| `UV_CACHE_DIR=.uv-cache uv build --wheel --out-dir /tmp/c1-m04-wheel` | 0 | PASS; [wheel check](../evidence/M04/wheel-check.md) |
| `UV_CACHE_DIR=/tmp/c1-uv-cache uv run --locked python -m scripts.demo_m04` | 0 | PASS; [sanitized result](../evidence/M04/demo.json) |
| `make stack-down` | 0 | PASS; [log](../evidence/M04/stack-down.log); volumes retained |

The first sandboxed `make check` could not bind loopback sockets for existing
unit tests; the exact gate passed after the required sandbox escalation. Two
pre-fix full integration attempts were intentionally stopped during M03
regressions after final review found the schema/history guard and receipt
paging proof gaps; [interruption evidence](../evidence/M04/integration-interrupted.md)
records them. The subsequent complete run is the gate result. Ordinary
`make check` skips live tests; only the explicit `C1_STACK=1` execution counts
as live evidence.

## Limits and next action

M04 relies on one host and one serialized writer. Pending or unreconcilable
cross-service publication remains denied and unready until repair. The trusted
catalog contains only the tested synthetic additive profile; incompatible
migrations are proposals, not executable changes. Direct administrative
database writes bypass the supported API. Already delivered bytes cannot be
recalled. Documents, query selection, and context packages belong to later
milestones.

No acceptance scope change was requested or approved for M04.

The next bounded action is to revalidate the provisional M05 plan against this
report and then implement only M05 under the owner's current authorization.
