# M02 — Canonical model and standards profile: execution report

**Gate:** VERIFIED

All M02-T01–T07 checks and applicable regressions passed.
Approved plan revision: `f3badde`. Implementation revision: `4be307fce53793c993cbc935f4bab56116060231`.
Execution date: 2026-09-27. The subsequent closure commit changes documentation
only. No unresolved gate failure remains and no later milestone was started.

## Delivered behavior

The core profile supplies canonical identities, typed records, independently
identified assertions, evidence, provenance, lexical literals, explicit keywords
and temporal qualifiers. Bundled JSON-LD and SHACL validate the supported subset;
unsupported input is rejected before any write or context fetch. Contradictory
claims and multiple relationships remain separate records.

The TerminusDB adapter preserves public IRIs and exact literal text, installs a
schema only in a fresh empty database, and allows data-only new profiles. A
profile digest covers its manifest, context and supplemental SHACL constraints.
Record reads and writes check schema definitions and the installed-profile
marker. Ordinary record writes cannot replace internal markers.

The 49-node synthetic fixture includes all 12 supported datatypes. Its real
backend export equals the frozen expected JSON-LD and is RDF-isomorphic to the
normalized input. No API endpoint, authorization plane, ChangeSet apply path,
query engine or model execution was introduced.

## Accepted decisions and corrections

The owner explicitly approved both questions on 2026-09-27, recorded in M02 §9:

1. Keep TerminusDB's default storage context and omit the unsupported backend
   `c1` prefix. Public JSON-LD and canonical URNs remain unchanged. The original
   form failed with HTTP 400 `api:PrefixDoesNotResolveError`.
2. Allow flat SHACL datatype alternatives alongside IRI/literal alternatives.
   Nested logic, scripts, remote imports and unsupported operators stay rejected.

D9's embedded `ValueHash` keys failed on repeated equal literals in one batch
with `api:SameDocumentIdsMutatedInOneTransaction`. Embedded values now use backend
`Random` keys; those IDs are not public RDF identities. Named resource identities
are unchanged. The failure and successful correction are recorded in
[subdocument-key-observation.json](../evidence/M02/subdocument-key-observation.json).

Named keyword/time/selector nodes remain separately named storage documents;
lexical values are typed subdocuments. Enum semantics are enforced by the record
and SHACL layers while retaining RDF literal text in storage. These internal
mapping corrections do not change the supported data contract.

D14's Python ceiling claim was incorrect: pySHACL metadata requires `>=3.9`;
classifiers through 3.13 are not an upper bound. C1 retains its tested Python
3.13 runtime. Python 3.14 remains NOT_RUN.

## Runtime and evidence

Python 3.13.14; TerminusDB 12.0.7; Podman 5.7.0; podman-compose 1.5.0.
Runtime libraries: Pydantic 2.13.5, RDFLib 7.6.0, pySHACL 0.40.1, HTTPX 0.28.1.
The service pins are unchanged from M01. The fresh complete
[inventory](../evidence/M02/m01-regression/final-integration/inventory.json)
records installed artifacts; [dependencies.json](../evidence/M02/dependencies.json)
and [license review](../evidence/M02/dependencies.md) cover the new dependencies.
Historical M01 evidence and both root source baselines were preserved.

| Exact command | Exit | Result/evidence |
|---|---|---|
| `make bootstrap` | 0 | PASS; locked environment installed |
| `make check` | 0 | PASS; 123 tests, lint, formatting, strict mypy, secrets, baseline and generated schema; [log](../evidence/M02/check.log) |
| `make stack-up` | 0 | PASS; [log](../evidence/M02/stack-up.log) |
| `C1_STACK=1 make integration` | 0 | PASS; 21 real-service tests, no skips; [JUnit](../evidence/M02/junit.xml), [log](../evidence/M02/integration.log), [command](../evidence/M02/final-integration-command.log) |
| `C1_STACK=1 make probe` | 0 | PASS; all 12 M01 tests; [commands](../evidence/M02/m01-regression/commands.log), [JUnit](../evidence/M02/m01-regression/junit.xml) |
| `uv run --locked python scripts/build_profile.py --check` | 0 | PASS; included in the final local gate |
| `make secrets baseline profile` | 0 | PASS; [precommit log](../evidence/M02/precommit-checks.log) |
| `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python UV_PYTHON_BIN_DIR=.uv-python/bin uv build --offline` | 0 | PASS; [build log](../evidence/M02/build.log), [isolated wheel import](../evidence/M02/wheel-check.log) |
| `make stack-down` | 0 | PASS; [log](../evidence/M02/stack-down.log) |

The 21 service checks skipped by default `make check` all passed in the separate
real-service run. The final integration run reported 12 RDFLib parser deprecation
warnings; these are not failed assertions. No mocked result substitutes for a
backend proof. An isolated extracted wheel loaded all 18 profile classes and
21 backend schema documents outside the checkout.

Earlier attempts exposed missing manifest references, formatting/type issues and
six secret-detector false positives, all fixed before the final gate. The
[detector audit](../evidence/M02/secret-audit.md) verifies the exact public-license
hashes and synthetic test placeholders; no scanner was disabled. Sandbox-only
attempts could not bind the no-fetch test's local socket. The permitted final run
executed that test successfully. A bare offline build could not write the default
user cache; the explicit repository-local cache command above succeeded.

## Named acceptance checks

| Contract | Result and executable evidence |
|---|---|
| M02-T01 supported round-trip | PASS; `test_t01_roundtrip.py`, `test_export.py`: all 12 datatypes, canonical IDs, qualifiers, provenance and repeated equal values survive real storage |
| M02-T02 malformed versus conflicting | PASS; `test_validation.py`, `test_t02_conflicts.py`: malformed records rejected; contradictory claims and two employments retained |
| M02-T03 unsupported input | PASS; `test_unsupported.py`, `test_t03_no_partial.py`: zero context-fetch requests; invalid batch leaves documents, head and log unchanged |
| M02-T04 identity independence | PASS; `test_identity_values.py`, `test_t04_identity.py`: changing labels/project/scope hints preserves identity; duplicate candidates never merge |
| M02-T05 keyword cases | PASS; `test_keywords.py` and fixed vectors: Unicode normalization, language-aware exact ANY/ALL, coalescing and empty filters |
| M02-T06 time cases | PASS; `test_time.py` and fixed vectors: precision, half-open intervals, unknown and unbounded state, timezone uncertainty |
| M02-T07 safe extension | PASS; `test_extension.py`, `test_t07_extension.py`: data-only extension round-trip, incompatible revision rejected without head/log/schema mutation |
| Installation guards | PASS; `test_install_guards.py`: real schema commit followed by injected marker-write failure blocks record reads/writes; forged marker write mutates nothing |

The supplemental [guard log](../evidence/M02/install-guards.log) and
[JUnit](../evidence/M02/install-guards-junit.xml) retain the narrow proof; the final
21-test JUnit also includes both guard cases. One local SHACL validation of the
49-record, 295-triple fixture took 0.030005 seconds; [timing](../evidence/M02/shacl-timing.json)
is an observation, not a capacity benchmark.

## Review and remaining boundaries

The stable diagnostic families exercised by these checks are:

| Code | Meaning |
|---|---|
| C1-IX-001 / 002 | Unbundled context / unsupported JSON-LD keyword |
| C1-IX-010 / 011 / 012 | Invalid or blank node / undeclared predicate / undeclared primary class |
| C1-IX-020 / 021 / 022 | Unsupported datatype / invalid lexical form / invalid language combination |
| C1-IX-030 | Structural or semantic record constraint |
| C1-IX-040 / 041 | Informational duplicate candidate / keyword coalescing |
| C1-PR-001 / 002 / 003 | Invalid manifest / context / unsupported shape |
| C1-PR-004 / 005 | Migration required / additive profile change |
| C1-ST-001 | Installation requires a fresh empty database |
| C1-ST-002 / 003 | Safe backend error / malformed backend response |
| C1-ST-004 / 005 | Rejected mapping or reserved ID / invalid stored representation |
| C1-ST-006 / 007 | Profile authority mismatch or forbidden upgrade / protected database lifecycle |

Independent review found a named Keyword could be removed while an Activity
still referenced it. The fixed coalescer checks all remaining IRI references;
a regression preserves that provenance link. Another independent review found
SHACL-only narrowing and same-ID context changes escaped compatibility checks.
Both now produce migration diagnostics, with regressions proving the formerly
valid data becomes invalid under the proposed narrowing.

Integration review corrected review-state names to `reported/confirmed/disputed`,
completed workflow-record field mappings, checked embedded schema definitions,
reserved profile markers, and sampled the repository head before installation
precondition checks so the backend CAS protects the checked state.

Explicit limitations, all within M02 scope:

- Schema installation and its marker projection are two commits. Incomplete
  projection fails closed in `read_records` and `write_records`. The demonstrated
  recovery is dropping and recreating the isolated fixture database; general
  recovery and migration execution are deferred. No cross-graph atomicity claim.
- Installation introduces a new profile; it refuses replacing an existing one.
  The pure comparison function classifies additive changes and migration needs.
  Context changes and changes to existing supplemental SHACL constraints are
  conservatively classified as requiring migration review.
- Each node has exactly one registered primary storage class; extra RDF types
  are retained. Backend shadows have explicit range/non-finite limits while
  original lexical values remain authoritative.
- Storage tools are internal fixture tools. Authorization, historical product
  reads, ChangeSet application and consumer queries remain later work. M03's
  provisional assumptions must be revalidated against this actual interface.
- Python 3.14 and production-scale performance are NOT_RUN. No AI dependency,
  credential, embedding service or new request endpoint is required.

## Reproducible demonstration and next action

Run from the repository with the locked environment and local stack:

```sh
make stack-up
C1_STACK=1 make integration
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python UV_PYTHON_BIN_DIR=.uv-python/bin uv run --locked python -m scripts.demo_m02 --fixture fixtures/core-knowledge
make stack-down
```

The demo creates and drops its own isolated database. Its
[output](../evidence/M02/demo.jsonld) matches the frozen expected JSON-LD exactly;
[verification](../evidence/M02/demo-verify.log) also confirms RDF isomorphism.
[Commands and exit codes](../evidence/M02/live-gate-commands.log) record the run.
The transport demo lives in `scripts.demo_m02`; the pure interchange export module
does not accept storage credentials or database routing.

Next bounded action: owner selection of M03 after revalidating its provisional
plan against this report. M03 implementation is not automatically authorized.
