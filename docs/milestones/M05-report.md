# M05 — Shared identity and deterministic query API: execution report

**Gate:** VERIFIED

The full M01–M05 live integration suite and M01 probe passed.

Approved plan: [M05.md](M05.md), authorized by the owner's request to
implement all planned, unimplemented milestones after M04 was verified.
Starting revision: `3ab3bdd9d4049181168d7a14dff490590f3dd5de`.
Implementation revision: `96175919eca77d0f146b7a3a477e26174a27eeae`.
Execution date: 2026-09-27.

## Delivered behavior

Authenticated clients can query the one shared repository through the catalog,
entity search and detail, assertions, sources, evidence, snapshot export, and
bounded neighborhood routes. Combined filters have a strict JSON grammar;
simple filters use URL parameters. Exact keyword language and normalization,
valid time, typed property and relation matching, review and lifecycle state,
and project narrowing operate on a fully authorized resource selection. Counts,
ordering, explanations, and traversal use that same selection. The API pins a
knowledge revision, signs expiring cursors, rechecks current authorization on
every continuation, and fails without a partial result on bounded-work errors.

Reviewed ChangeSet identity operations provide explicit resolution, merge,
split, and compensating undo. Complete assertion reassignment is required;
assertion bindings are retained. A redirect is visible only when the merged
identity, survivor, and resolution are readable. The synthetic directory has
one Person ID across two companies and independently protected contact claims.
Its service principal authored the fixture ChangeSet and Carol independently
reviewed it through ordinary authenticated APIs.

The implementation adds no model runtime, embedding service, or AI provider
key. [The local no-AI check](../evidence/M05/no-ai-check.md) records the
configuration-name check.

## Decisions and review

[ADR-0013](../decisions/ADR-0013-authorized-selection.md) records the
workflow-head-bound candidate projection and full current authorization of
every provisional candidate before content matching or counts. A final fresh
authorization pass precedes release. [ADR-0014](../decisions/ADR-0014-reviewed-identity.md)
records reviewed identity expansion, complete reassignment, policy preservation,
and the same-scope entity merge guard. The pinned TerminusDB GraphQL path can
coerce decimal lexical values; affected chunks use the bounded per-ID document
fallback. The route implementation consolidates the plan's separate route-file
sketch into `query.py` to share strict parsing and error handling.

Review found and fixed hidden-reference empty-field differences, hidden IDs
affecting visible organizational IRIs, and unreadable time boundaries being
mistaken for unbounded time. Direct reads now use the same declared content
reference distinction as queries, and a hidden essential interval or boundary
cannot silently qualify an assertion. Traversal cursors now sign a compact
offset and current selection fingerprint and replay the bounded deterministic
prefix; a default 200-edge page stays decodable. Focused real-service tests
cover these findings. The initial directory script import and synthetic ID
format errors were corrected before its successful run. No acceptance scope
change was made.

## Runtime and checks

Python 3.13.14; pinned TerminusDB 12.0.7, OpenFGA 1.21.0, Keycloak 26.7.4,
and PostgreSQL 17-alpine. The Python lock and service image digests are unchanged
from M04. M05 integration tests use synthetic principals, isolated knowledge
and workflow databases, and isolated OpenFGA stores. The shared-directory demo
used the configured local development database and is recorded with IDs and
counts only in [directory-demo.md](../evidence/M05/directory-demo.md).

| Named check | Executable coverage | Result |
|---|---|---|
| M05-T01 | `test_t01_directory.py`: one Person ID, four assertion policies, export and history | PASS |
| M05-T02 | `test_t02_filters.py`: combined filters, language, time, recorded order, hidden temporal bound | PASS (2 cases) |
| M05-T03 | `test_t03_noninterference.py`: hidden entity, keyword, edges, direct read, byte-identical observations | PASS |
| M05-T04 | `test_t04_identity_m05.py`: rename, merge, split, undo, preserved policies and hidden duplicates | PASS |
| M05-T05 | `test_t05_cursors.py` and unit traversal regression: pinned pages, revocation, ordinary continuation, re-scope restart, 200-edge cursor | PASS (2 live cases) |
| M05-T06 | `test_t06_limits.py` and `test_plan.py`: page/depth/5000-candidate/500-scope/time bounds, raw-query denial, hidden/nonexistent parity | PASS (3 live cases) |
| M05-T07 | `test_t07_views.py`: project narrowing, hidden project IRI collision, no copied identity or grant | PASS |
| Backend fetch | `test_backend_fetch.py`: pinned GraphQL `ids` and document fallback | PASS |

| Exact command | Exit | Result/evidence |
|---|---|---|
| `make bootstrap` | 0 | PASS; [log](../evidence/M05/bootstrap.log) |
| `make check` (loopback-capable sandbox) | 0 | PASS; 281 unit and nonlive tests, 65 live skips; [log](../evidence/M05/check.log) |
| `make secrets baseline profile` | 0 | PASS after the report gate marker was formatted for the baseline checker; secret scan covered 393 tracked/nonignored files |
| `make stack-up` | 0 | PASS; pinned local services ready; [log](../evidence/M05/stack-up.log) |
| `uv run --locked python scripts/load_fixture.py --fixture directory --database c1_m03_dev_knowledge` | 0 | PASS; [demo evidence](../evidence/M05/directory-demo.md) |
| `uv run --locked python scripts/demo_m05.py` | 0 | PASS; same Person ID, assertion counts 3/2/5/2 |
| `C1_STACK=1 make integration` | 0 | PASS; 65 tests, 0 failures/errors/skips in 2844.389 s, including 12 M05 cases; [summary](../evidence/M05/integration.log), [JUnit](../evidence/M05/integration-junit.xml) |
| `C1_STACK=1 make probe` | 0 | PASS; 12 tests, 0 failures/errors/skips in 54.14 s; [summary](../evidence/M05/probe.log), [JUnit](../evidence/M05/probe-junit.xml) |
| `UV_CACHE_DIR=.uv-cache uv build --wheel --offline --out-dir /tmp/c1-m05-wheel` | 0 | PASS; [wheel check](../evidence/M05/wheel-check.md) |
| `PYTHONPATH=. uv run --locked python /tmp/c1_m05_index_timing.py` | 0 | PASS; 12 bindings, cold build 351.88 ms, same-head reuse 111.60 ms; [sample](../evidence/M05/index-timing.md) |
| `make stack-down` | 0 | PASS; volumes retained; [log](../evidence/M05/stack-down.log) |

Ordinary `make check` skips live tests. Initial un-escalated execution could
not create loopback sockets for existing unit tests; the named check passed
with the required local socket access. Exploratory live runs were stopped when
the review found issues; their partial results are not counted as the gate.
The frozen directory output matched its expected IDs and counts; no output
diff remained. The pinned backend fetch test exercised GraphQL `ids` and the
document fallback. The index timing is one development-host sample, not a
throughput claim. The full integration suite retained 14 upstream rdflib
deprecation warnings; the probe retained 3.

## Limits and next action

The 5000-candidate, fewer-than-500-readable-scope, and 2-second request limits
can return an explicit error on larger selections. A failed or inconsistent
current security state fails closed. The workflow-head projection assumes all
supported security writes use C1's journal; direct out-of-band OpenFGA edits
are outside the coordination protocol. Successful-response noninterference is
tested for the synthetic fixture; identical latency or availability under any
hidden-state change is not claimed. No query endpoint exposes raw backend
queries, and M05 does not implement documents or context packages.

The next bounded action is M06 planning after owner authorization. No M06
implementation is started by this report.
