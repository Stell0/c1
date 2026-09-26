# M01 — Infrastructure and feasibility proofs report

**Gate:** VERIFIED

**Approved plan revision:** `d045ab4200f37c065cf7ea50033911f40be5acd9`,
authorized by the owner's M01 implementation and commit/push request. Execution
corrections are recorded in M01 §9; roadmap acceptance criteria are unchanged.
**Implementation revision:** `f19bd18195278a76170c90aeb8df86bcc86f8ccf`,
committed and pushed to `origin/main`. This closure update changes only the
report/evidence; tested runtime inputs are unchanged. The accompanying
`docs/evidence/M01/implementation.sha256`
identifies tested inputs without circular report/evidence hashes.
**Report date:** 2026-09-26.

## Delivered scope

A pinned local TerminusDB/OpenFGA/PostgreSQL/Keycloak development stack, random
private credentials, bounded readiness checks, an offline artifact inventory,
three ADRs, and isolated executable probes. Knowledge, workflow, authorization
and interchange experiments live outside `src/c1`. There is no product API,
Explorer, AI runtime or M02 implementation.

## Environment and reproducibility

Linux x86_64, Python 3.13.14, uv 0.12.2, Podman 5.7.0,
podman-compose 1.5.0. Four actual image index/platform/configuration identities
are in [inventory.json](../evidence/M01/inventory.json) and
[the readable inventory](../evidence/M01/inventory.md): TerminusDB v12.0.7,
OpenFGA v1.21.0, Keycloak 26.7.4 and PostgreSQL 17.11.
[versions.log](../evidence/M01/versions.log) records exact runtime commands and outputs.
Forty-two installed Python distributions match `uv.lock`, including httpx 0.28.1,
openfga-sdk 0.10.4, rdflib 7.6.0 and pyshacl 0.40.1. Installed license-file hashes
and notice presence are recorded. Source-tag primary image license texts are
bundled; absent embedded candidates are reported explicitly, not invented.
[License review](../evidence/M01/license-review.md) resolves metadata ambiguities
against 48 installed license files.

From the repository root, with Podman and podman-compose installed:

```sh
make bootstrap
make stack-up
make inventory
C1_STACK=1 make probe
make check
make stack-down
```

The stack publishes only loopback ports. No six named AI-provider environment
variables were set during the recorded gate. Fixtures are synthetic. Each probe
creates fresh knowledge/workflow databases and an OpenFGA store, then removes
them. Fault injection pauses/kills only the owned `c1-dev` OpenFGA container and
restarts it in `finally`. Run the gate sequentially on this dedicated stack.
Default `make check` intentionally skips the live integration group; this is
not counted as its passing evidence. Explicit `make probe` requires `C1_STACK=1`.

## Commands and regressions

| Command | Exit | Result |
|---|---:|---|
| `make stack-up` | 0 | PASS; three HTTP readiness checks, PostgreSQL-dependent startup |
| `make inventory` | 0 | PASS; four real images, 42 installed distributions |
| `C1_STACK=1 make probe` | 0 | PASS; 12 live tests covering T01–T07 |
| `make check` | 0 | PASS; lint, formatting, strict mypy, 28 tests; 12 live tests intentionally skipped in this separate invocation; secret and baseline checks |
| `git diff --cached --check` | 0 | PASS; exact upstream license EOF bytes retained via file-specific whitespace attribute |
| `bash scripts/clean_start.sh --worktree` | 0 | PASS; clean disposable checkout, interpreter and dependency environment |
| `make stack-down` | 0 | PASS; development volumes preserved |
| `gh run watch 36261615854 --exit-status --interval 10` | 0 | PASS; remote bootstrap and full default check at the implementation SHA |

The full regression output is [check.log](../evidence/M01/check.log);
[clean-start.log](../evidence/M01/clean-start.log) records the independent fresh environment.
[Secret review](../evidence/M01/secret-audit.md) found no new candidates and
made no baseline or detector exceptions.
GitHub [CI run 36261615854](https://github.com/Stell0/c1/actions/runs/36261615854)
passed at the exact implementation revision; [ci.json](../evidence/M01/ci.json)
records the result. CI runs the default gate, with real-service tests skipped;
the 12-test local pinned-stack run supplies those results. GitHub noted the
existing pinned checkout action's Node 20 deprecation and automatic Node 24
execution; the action and all checks succeeded.

## Named gate checks

The complete executed command transcript is
[commands.log](../evidence/M01/commands.log); machine-readable test results are
[junit.xml](../evidence/M01/junit.xml).

| Check | Result | Evidence and bounded conclusion |
|---|---|---|
| M01-T01 artifact check | PASS | Four pinned local images and installed locked distributions; license files/hashes, embedded candidate paths, no forbidden stack flags. |
| M01-T02 atomic batch | PASS | Invalid third document leaves head/log/documents unchanged; valid batch creates exactly one knowledge commit with durable receipt metadata, then a workflow projection. |
| M01-T03 stale base and lost response | PASS | Backend rejects stale header with HTTP 400; lost acknowledgement reconciles once; different payload/key reuse fails; different principal remains independent; old receipt remains discoverable after twelve later commits. |
| M01-T04 immutable revisions | PASS | Distinct old/current values, history and diff; deletion preserves old revision reads. T05 proves those reads use current security state. |
| M01-T05 policy freshness | PASS | Rebinding with retained group membership, revocation, missing/ambiguous bindings and historical reads deny correctly. Real pause timeout and kill deny; recovery restores reads. |
| M01-T06 publication recovery | PASS | Three real subprocess exits between durable steps block reads; fresh reconciliation produces one content commit and valid binding; repeated replay is a no-op. Invalid content leaves a failed journal deny tombstone. |
| M01-T07 interchange | PASS | Real storage round trip is RDF-isomorphic, retaining assertion IRI, language, decimal datatype and provenance. Remote context rejection yields zero HTTP requests, no new commit and no document. |

The real-service gate passed **12 tests** (exit 0). `make stack-up` and
`make inventory` also returned exit 0.

Journal latency measurements are printed for each recovered crash point in the
command transcript: nine recovered journal writes ranged from **74.99 to 109.94 ms**.
They measure individual workflow journal write calls,
including expected-head lookup, on this host; they are not a production SLA.

## Review, fixes and limits

An independent bounded review of publication, writer, FGA and session code found
two issues: the provisional deny-tuple description did not match the model, and
store creation could leak a test store if model initialization failed. M01 §9
now specifies the durable failed journal as the tombstone; cleanup registration
now precedes store/model initialization. The reviewer found no further concrete
fail-open or crash-retry defect in that scope.

Live implementation exposed and fixed an absent-document response quirk using
`as_list=true`, prohibited custom-context POST (preserve the default context),
and class-specific document ID prefix requirements. Ruff/type issues were fixed.
RDFLib emits deprecation warnings about its internal ConjunctiveGraph use; the
round-trip assertions pass. No security check was removed to pass the gate.

These are foundations with explicit remaining obligations:

- Sequential freshness is proven. Arbitrary concurrent policy changes do not take
  the local publication lock; M03 must coordinate those changes with reads and
  publication. No distributed transaction or multi-host writer proof is claimed.
- Mixed schema/instance commits, arbitrary ChangeSet operations, multi-scope
  transactions and compensating restores are NOT_RUN here; later milestone gates
  must prove the selected methods. Only the tested document-batch operation is
  accepted by this milestone.
- Keycloak startup/import/discovery pass. Login, JWT validation and product
  identity readiness are M03 work; PyJWT is therefore not an M01 dependency.
- The narrow RDF term mapping is an experiment, not M02's canonical schema.
  Full OWL reasoning and external context fetching remain disabled.
- Upstream images are run directly. Complete redistribution notices, base-image
  dependency review, production hardening and packaging remain M13 obligations.
  Source-tag fallback evidence does not claim an embedded license was found.

No acceptance criterion was waived and no later milestone was started. After
verification, the bounded next action is owner selection/planning of M02.
