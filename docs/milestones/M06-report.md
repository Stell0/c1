# M06 — Scoped documents and reconstruction: execution report

**Gate:** VERIFIED

The post-alias combined real-service run completed with 71 of 72 tests passing.
All seven M06 cases and the M01–M04 regressions passed. The sole failure was
M05 T04: its long-running fixture reused a cached token that expired. The
test-only helper now refreshes real tokens, and the full M05 group rerun passed
all 12 cases against the final input snapshot. Therefore all named M06 checks
and M01–M05 regression checks passed across the combined run and the M05
rerun. The initial combined command still records its actual exit-1 result;
it is not represented as a single all-pass invocation. M07 implementation had
not started when this gate closed.

Approved plan: [M06.md](M06.md), authorized by the owner's request to implement
planned, unfinished milestones and commit/push each completed milestone.
Original plan revision: `f4c828e97289e05d9e2ed48de3bf89cd48264374`.
Starting revision: `29ddc193cd28ff777b62daf21caea35e0b83f6d5`.
Implementation revision: `b1c2b1a3b65fe7d07de5c539e3f2b30b643eb003`.
The final source manifest matches this implementation commit; this closure
adds its revision to the report without changing tested source inputs.
Execution date: 2026-09-28 (Europe/Rome).

## Delivered behavior

Authenticated document routes provide listing, normalized substring search,
ordered readable parts, compact reconstruction, Markdown/plain-text rendering,
export, and history. Every read uses M05's authorized selection and final
current-security check. Historical knowledge uses current bindings. Hidden
parts do not enter matching, ordering, counts, renderer input, or export.

ChangeSet validation checks flat structure, readable parent documents, rank
grammar, text controls and UTF-8 size, evidence selectors, and source revisions.
Insertion and structural moves require the affected document permissions.
Default inheritance is resolved before proposal review; content moves and
restores preserve current security bindings. Request idempotency hashes the
submitted payload independently of current default-binding resolution.

Structured DocumentPart records preserve submitted Unicode text and formatting
exactly; each part digest covers its text's UTF-8 bytes. Plain-text rendering
uses a heading's title when present, otherwise its text, emits other part
bodies as text, and separates parts with one blank line. Markdown applies its
documented escaping and code-fence rules, labels source-code excerpts, and
never executes source content or fetches external resources. The synthetic fixture spans
three scopes and two revisions; the loader uses ordinary authenticated
ChangeSets with a separate reviewer. [API notes](M06-api.md) describe the
request/response contract.

## Decisions and review

[ADR-0015](../decisions/ADR-0015-documents.md) records ordering, encoding,
projection, rendering, evidence versioning, and inheritance semantics.
The implementation refines the original plan's global rank uniqueness:
rejecting a collision with an unreadable sibling would expose its rank.
Equal ranks therefore sort by canonical part IRI. PLAN.md's deterministic
ordering acceptance contract is retained.

Review found and fixed mismatched inheritance parents, missing document write
permissions, reviewer visibility for staged documents, selector source-version
checks, part retyping rejection, moved-out part history, stale history cursors,
repeated per-part history checks, and reconstruction limits incorrectly blocking
pagination. Test review corrected a nonexecuting Bob
assertion and expanded hidden-state comparisons across every document view.
Plain text remains exact JSON data; the plan's contradictory requirement to
escape plain text like Markdown was clarified without changing its rendering
safety or text-integrity contracts.
The [review record](../evidence/M06/review.md) separates code review from the
executed live gate; it is not a substitute for passing acceptance checks.

Final transport review found that supported document IRIs ending in an
operation suffix could not reach the detail path. An authenticated `by-id`
query route removes that ambiguity while reusing the same detail service.
The first combined run was interrupted during T04 after T01–T03 passed;
its [log](../evidence/M06/m01-m06-pre-alias-interrupted.log) and
[JUnit](../evidence/M06/m01-m06-pre-alias-interrupted.xml) are incomplete
evidence, not a passed gate. The full gate is restarted after the route fix
and added transport/privacy coverage.

## Runtime and evidence

Python 3.13.14; pinned TerminusDB 12.0.7, OpenFGA 1.21.0, Keycloak 26.7.4,
and PostgreSQL 17-alpine. Dependency locks and image digests are unchanged.
The probe's [runtime inventory](../evidence/M06/m01-inventory.json) records the
inspected service images and Python packages.
The [combined-run implementation snapshot](../evidence/M06/implementation-snapshot.md)
records checksums for 271 source, test, fixture, profile, deployment, and
secret-baseline inputs. The [final rerun snapshot](../evidence/M06/final-implementation-snapshot.md)
adds only the scoped M05 T04 test-helper change; production source inputs are
unchanged.
Live tests use synthetic principals, isolated knowledge/workflow databases,
and isolated OpenFGA stores. No AI configuration names were present in the
process environment or local deployment configuration; see the
[names-only check](../evidence/M06/no-ai-check.md).

| Named check | Coverage | Result |
|---|---|---|
| M06-T01 | Three authorized ordered projections at two revisions; JSON/Markdown/text goldens | PASS in post-alias combined run |
| M06-T02 | No protected structure; all public views equal an isolated hidden-deletion fixture | PASS in post-alias combined run |
| M06-T03 | Hidden-only/duplicate search terms, authorized export, explicit Bob legal-part checks | PASS in post-alias combined run |
| M06-T04 | Historical re-scope, restore retaining binding, move-out history and cursor restart | PASS in post-alias combined run |
| M06-T05 | Exact Unicode/whitespace/digest, 200 KiB body, NUL/C1-control and 300 KiB rejection | PASS in post-alias combined run |
| M06-T06 | Invalid structure/version/selectors, denied writes, equal ranks, default inheritance and move binding preservation | PASS in post-alias combined run |
| M06-T07 | Adversarial Markdown, exact JSON/plain text, zero local TCP fetches | PASS in post-alias combined run |

| Exact command | Exit | Result/evidence |
|---|---|---|
| `make bootstrap` | 0 | PASS; [log](../evidence/M06/bootstrap.log) |
| `UV_OFFLINE=1 make check` (loopback-capable execution) | 0 | PASS; 381 passed, 72 live skips, 16 warnings in 21.08 s; [log](../evidence/M06/final-check.log) |
| `UV_OFFLINE=1 make lint secrets baseline profile` | 0 | PASS after final document/snapshot updates; [log](../evidence/M06/final-doc-check.log) |
| `make stack-up` | 0 | PASS; local pinned services ready |
| `UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python scripts/load_fixture.py --fixture scoped-document --database c1_m03_dev_knowledge` | 0 | PASS; [log](../evidence/M06/fixture-load.log) |
| `UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python scripts/demo_m06.py` | 0 | PASS; Alice 3/Carol 7 parts and Markdown golden equality; [evidence](../evidence/M06/document-demo.md) |
| `UV_CACHE_DIR=.uv-cache uv build --wheel --offline --out-dir /tmp/c1-m06-wheel` | 0 | PASS; [wheel check](../evidence/M06/wheel-check.md) |
| `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY -u HF_TOKEN -u AZURE_OPENAI_API_KEY C1_STACK=1 UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked pytest -q --tb=line --show-capture=no -p no:cacheprovider -p tests.integration.m06.diagnostics --junitxml=docs/evidence/M06/m01-m06-junit.xml tests/integration/m06 tests/integration/m01 tests/integration/m02 tests/integration/m03 tests/integration/m04 tests/integration/m05` | 1 | FAIL: all 72 tests completed; 71 passed, 1 failed, 0 errors/skips in 6659.63 s. The failure was M05 T04 after its cached test token expired; XML/log were renamed to [before-token-fix evidence](../evidence/M06/m01-m06-before-token-fix.xml) and [log](../evidence/M06/m01-m06-before-token-fix.log). |
| `C1_STACK=1 UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked pytest -s -m integration tests/integration/m01 -p no:cacheprovider --tb=line --show-capture=no --junitxml docs/evidence/M06/m01-probe-junit.xml` | 0 | PASS; 12 tests in 52.21 s; [log](../evidence/M06/m01-probe.log), [JUnit](../evidence/M06/m01-probe-junit.xml) |
| M01–M04 real-service regressions | — | PASS, 53 cases within the combined command above (which exited 1 on M05 T04) |
| `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY -u HF_TOKEN -u AZURE_OPENAI_API_KEY C1_STACK=1 UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv run --locked pytest -q --tb=line --show-capture=no -p no:cacheprovider -p tests.integration.m06.diagnostics --junitxml=docs/evidence/M06/m05-after-token-fix.xml tests/integration/m05 > docs/evidence/M06/m05-after-token-fix.log 2>&1` | 0 | PASS; 12 passed, 0 failures/errors/skips in 1455.99 s; [log](../evidence/M06/m05-after-token-fix.log), [JUnit](../evidence/M06/m05-after-token-fix.xml), using [final input snapshot](../evidence/M06/final-implementation-snapshot.md) |
| `UV_OFFLINE=1 make stack-down > docs/evidence/M06/stack-down.log 2>&1` | 0 | PASS; isolated test stack stopped, volumes retained; [log](../evidence/M06/stack-down.log) |

The first complete M06 live run returned 1 PASS and 6 FAIL in 2377.69 s.
T02 exceeded the history deadline; T03/T04/T05/T07 used expired test-client
tokens; T06's atomicity snapshot used an unsupported OpenFGA Read filter.
These failures are retained as failure evidence and must be superseded by
executed passing checks, not by inspection. Test clients now obtain ordinary
fresh tokens for the same principals; no server token lifetime or verifier was
relaxed. History preserves the two-second limit and current-security boundary.

The second complete run returned 4 PASS and 3 FAIL in 2763.74 s. T01–T03
and T07 passed. T04 selected the wrong canonical fixture records for its
replacements; T05/T06 treated the test's Terminus client as a wrapper around
another client. These test-helper errors were corrected. Review also
identified a race between the workflow manifest enumeration and the
authorization plan; history must bind both to the same workflow head before
using complete storage-class hints.

The focused T04–T06 run returned 2 PASS and 1 FAIL in 1301.93 s: historical
authorization and exact large-text integrity passed. T06 incorrectly expected
a reference diagnostic for a valid Entity payload used to attempt retyping a
part. This case has a generic `permission_denied` preview and no record
diagnostic. Missing and unreadable parents both retain the same
`C1-CS-010 Unresolved reference` diagnostic, HTTP 403, and generic permission
preview. An intermediate rerun failed because its test incorrectly required
empty diagnostics for these parent references. The corrected assertions retain
indistinguishable missing/unreadable reports and unchanged knowledge and
security state. The final focused T06 rerun passed in 593.77 s; its
[log](../evidence/M06/m06-t06.log) and [JUnit](../evidence/M06/m06-t06.xml)
retain the executed result. The combined gate reruns all seven M06 checks and
all earlier milestone regressions against the frozen inputs.

The initial restricted `make check` could not create sockets for existing
local HTTP tests. It passed with loopback access. Exploratory live runs stopped
before completion to repair test coverage are not counted as a passed gate.
After the alias fix, the local tests passed but the secret scanner flagged
the unused `synthetic` OpenFGA token literal in the mocked route test. Its
existing-baseline exception was explicitly audited as a false positive;
detectors and filters are unchanged. The subsequent complete local gate
passed. The [initial log](../evidence/M06/check-alias-first.log) retains that
failed scanner result without the finding's source value.

The first closure check correctly rejected the roadmap/report status mismatch:
PLAN.md used `VERIFIED` while the report used `PASS`. The report now uses the
required `VERIFIED` status. This documentation error did not change the
executed service results.

| Closure command | Exit | Evidence |
|---|---|---|
| `UV_OFFLINE=1 make lint secrets baseline profile` | 0 | PASS; [closure check](../evidence/M06/closure-check.log) |

Raw failed-run logs and JUnit retain their original whitespace; a staged
whitespace check reported only those preserved evidence lines.

## Limits and next action

Parts are flat. Reconstruction/export has a 2000-readable-part bound; paging
allows 200 parts and remains usable beyond the reconstruction bound, subject
to the earlier 5000-candidate repository limit. History assembly bounds
readable candidates and revisions at 2000 and fails explicitly on exhaustion.
Requests use the configured
2-second budget and fail explicitly without partial reconstruction. Rank
intervals are finite and can exhaust; equal ranks use stable IRI tie-breaking.
Markdown is an escaped display format, not executable source. Exact source is
available in structured parts; non-heading text bodies are also preserved
in plain-text rendering.

The post-alias combined run's sole failure is isolated to the M05 T04 test
helper's cached-token lifetime; the real API correctly returned 401 after the
cached token expired. The scoped test helper now requests a fresh real token
for each action. The complete M05 group passed with this fix; the production
token validator and token lifetime were not relaxed. All M06, M01–M05, and
M01 probe checks passed, and the local stack was stopped with volumes retained.
The next bounded action, authorized by the owner, is to revalidate and
implement M07 after pushing the M06 implementation and report closure.
