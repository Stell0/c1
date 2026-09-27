# M03 — Identity and current resource authorization: execution report

**Gate:** IN_PROGRESS — final real-service gate and closure pending.

Approved plan revision: `88d40ed`. Starting revision: `7db3326`.
Implementation revision will be recorded after the verified implementation commit.
Execution date: 2026-09-27.

## Delivered behavior

The single configured API authenticates real Keycloak human and service access
tokens and provides audited security administration. Current OpenFGA grants and
current workflow bindings govern every protected synthetic resource read,
including historical knowledge commits. Scope creation, membership, resource
publication, reviewed re-scoping and recovery use durable journal operations.

Capabilities remain independent: operator, access administrator and reviewer
do not implicitly read content. Missing, duplicated or inconsistent bindings,
pending transitions and unavailable security services deny access. Hidden and
nonexistent resources return the same Problem Details response. Client fields
cannot choose the principal, database, repository, store or issuer.

The API has no ordinary knowledge CRUD or ChangeSet endpoints. Probe routes
are disabled by default and restricted to synthetic `urn:c1:probe:` identities.
They provide the small publication/read/revision surface required for M03 proofs.
No LLM, model service, provider key or later milestone was introduced.

## Execution decisions and review

[M03 §9](M03.md#9-execution-revalidation) and
[module contracts](M03-interfaces.md) record revalidation against actual M02 code.
The configured adapter needed narrow historical reads and internal replacement
for the two-version probe. The workflow database uses separate operational
envelopes and atomic CAS updates; it is not a second knowledge graph.

The 30-second token leeway requires the one-second expiry fixture to wait beyond
that interval. Keycloak omits optional `nbf`; it is validated when present.
JWKS caching is distinct from authorization caching: cached trusted keys can
validate already-issued tokens during issuer downtime, while readiness fails.

Native OpenFGA HTTP requests use higher consistency and a two-second timeout.
The bundled native model is installed by trusted setup and its immutable ID is
configured at startup. Readiness verifies that configured model is reachable.
Native JSON responses normalize field names and defaults, so raw JSON equality
is not used as a policy interpreter. Direct BatchCheck is covered separately
from the safe sequential fallback.

Independent review found and fixed three issues: canonical keyword normalization
was discarded before publication confirmation; completed self-revocation needed
monotone journal recovery after loss of actor authority; pending probe revisions
needed exact current-binding checks during recovery. Focused regressions cover
these fixes. Cascade review also checks that new inherited children make an
approval stale, while explicitly scoped children remain independent.

The first aggregate gate passed 36 tests and failed the historical-record
comparison because backend Set ordering differed from Python list ordering.
The same assumption also affected publication confirmation. Both now compare
RDF terms independently of order while retaining exact literal lexical text,
datatype, language, identity and type. Seven focused comparison regressions and
a live multi-value publication/revision regression accompany the correction.
The [initial failure](../evidence/M03/initial-gate/integration.log) is retained;
only the subsequent complete gate determines completion.

Final privacy review also moved probe creation authorization ahead of duplicate
lookup. Unauthorized creators now get the same denial for existing and new IDs;
only a readable existing resource gets a duplicate conflict. Hidden bindings or
unbound content produce a generic not-found response without content disclosure.
Unit and real API regressions cover these cases without mutating knowledge or
security state on rejection. Synthetic probe IDs remain caller supplied; general
identity allocation and reuse belong to the later knowledge-write contract.
Its initial live test setup used an unsupported unfiltered OpenFGA tuple read;
the [fixture failure](../evidence/M03/privacy-fixture-failure/integration.log)
occurred before any privacy assertion. The corrected test snapshots every known
scope, resource and instance object, and its [focused rerun](../evidence/M03/privacy-regression.log)
precedes the final aggregate gate. No product behavior was changed for that fix.

The crash-test launcher initially timed out before the API's backend timeout.
Its HTTP polling deadline now accommodates the bounded readiness check; actual
process exit and durable state are still asserted. Initial lint/format failures
were corrected before the closure gate. Secret-scan exceptions are limited to
audited public artifact digests, synthetic negative-test values and disposable test-store request paths.

The decisions are detailed in [ADR-0008](../decisions/ADR-0008-identity-boundary.md),
[ADR-0009](../decisions/ADR-0009-current-bindings.md), and
[ADR-0010](../decisions/ADR-0010-security-publication.md).

## Runtime and reproducibility

Python 3.13.14; TerminusDB 12.0.7; OpenFGA 1.21.0; Keycloak 26.7.4.
Service digest pins are unchanged from M01. The fresh [artifact inventory](../evidence/M03/m01-regression/integration/inventory.json) records the installed environment. Added runtime dependencies and their
actual license files/hashes are recorded in the
[dependency review](../evidence/M03/dependencies.md). The lock retains all exact
transitive versions. The installed wheel includes the native authorization model.

| Named check | Executable coverage | Result |
|---|---|---|
| M03-T01 | `test_t01_tokens.py`, unit `test_tokens.py` and `test_config.py`: invalid tokens, real human/service tokens, ignored delegation | PASS |
| M03-T02 | `test_t02_separation.py`: read, contribute, review, administration and operator separation; immediate revoke | PASS |
| M03-T03 | `test_t03_independent.py`: entities do not reveal protected assertions/evidence; project references grant nothing | PASS |
| M03-T04 | `test_t04_historical.py`: current binding denies head and historical reads after re-scope | PASS |
| M03-T05 | `test_t05_bindings.py`: missing/duplicate/unknown/transitioning/revoked bindings, retirement and inheritance | PASS |
| M03-T06 | `test_t06_crash.py`, `test_authority_contract.py`, `test_cascade.py`: three actual process crashes, authority negatives, stale cascade | PASS |
| M03-T07 | `test_t07_boundary.py`, unit boundary/privacy tests: selectors, injected policy, bounded requests, hidden duplicate protection and real outages | PASS |
| Supporting storage | `test_journal_contract.py`: atomic journal CAS and rollback, historical reads | PASS |
| Supporting batch | `test_authority_contract.py`: native and plane BatchCheck across 51 resources | PASS |

All integration fixtures use isolated disposable stores/databases and synthetic
principals. Their teardown removes test-owned stores and databases; the local
development databases and service volumes are retained. Safe
[token claims](../evidence/M03/token-claims.json),
[audit events](../evidence/M03/audit-sample.jsonl),
[crash outcomes](../evidence/M03/crash-recovery.json) and
[development store/model IDs](../evidence/M03/backend-ids.json) contain no tokens
or credentials. Crash evidence records the explicit intermediate 503 readiness,
404 read denial, and final exactly-one binding at each boundary.

| Exact command | Exit | Result/evidence |
|---|---|---|
| `make bootstrap` | 0 | PASS; [locked environment](../evidence/M03/bootstrap.log) |
| `make check` | 0 | PASS; 185 tests, lint, formatting, strict mypy, secret audit, baseline and generated profile; [log](../evidence/M03/local-gate.log) |
| `make stack-up` | 0 | PASS; idempotent real bootstrap; [log](../evidence/M03/stack-up.log) |
| `make api-up`, authenticated HTTPX `GET /v1/whoami`, `make api-down` | 0 | PASS; documented loopback helper, real Alice token and ready 200; [log](../evidence/M03/api-smoke.log) |
| `C1_STACK=1 make integration` | 0 | PASS; 39 live tests, no skips; [JUnit](../evidence/M03/junit.xml), [log](../evidence/M03/integration.log) |
| `C1_STACK=1 make probe` | 0 | PASS; all 12 M01 tests; [log](../evidence/M03/probe.log), [JUnit](../evidence/M03/m01-regression/probe/junit.xml) |
| `UV_CACHE_DIR=.uv-cache uv build --offline --wheel --out-dir /tmp/c1-m03-wheel` | 0 | PASS; [build log](../evidence/M03/wheel.log), API and exact bundled model present in wheel |
| `make stack-down` | 0 | PASS; containers stopped, volumes retained; [log](../evidence/M03/stack-down.log) |

The earlier sandboxed dependency download failure in
[static-checks.log](../evidence/M03/static-checks.log) was resolved by the
authorized bootstrap; it is not a passing check. RDFLib deprecation warnings
remain visible in test logs and do not indicate a gate failure.

The 39 real tests are deliberately skipped by ordinary `make check`; only a successful
`C1_STACK=1` execution counts as the integration gate. Earlier M01/M02 evidence
is preserved byte-for-byte, with newly generated regression artifacts captured
under M03 instead.

## Limits and next action

One process owns security and knowledge mutation on one host. Lifetime file
ownership rejects a second writer; this is not multi-host coordination. Direct
backend administrative changes bypass the supported product protocol.
Unresolvable pending recovery stays denied and unready until operational repair.
Authority loss does not silently publish content. Already delivered bytes cannot
be recalled.

The principal subject profile supports the pinned Keycloak UUID subjects;
other issuer subject syntaxes need explicit mapping design. Development password
grant clients and fixture users are not production identity configuration.
Browser sessions, public knowledge writes, query enumeration, production
deployment and complete redistribution notices remain outside this gate.

The next bounded action is to plan M04 using the verified M02 and M03 reports.
M04 has not been started.
