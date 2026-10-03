# M12 — Human Explorer: execution report

**Gate:** VERIFIED

Approved plan: [M12](M12.md), plan revision `9011325`. The owner authorized implementation on 2026-10-03 ("Try to install playwright on makako and start implementation"). That authorization settled OD2 (browser cases run on makako) and adopted the plan's recommendations for OD1 (server-rendered pages, no client script), OD3 (three public API additions) and OD4 (in-memory sessions).

Implementation revision: `8d5dacc`. The milestone was verified on the 538-input source in [`implementation-files.sha256`](../evidence/M12/implementation-files.sha256), whose own SHA-256 is `51d2fe94f30c292709578ad565ce0580bf8790d29f215560f3c74e395faed3a1`. The manifest matched [before](../evidence/M12/makako-manifest-check-before-gate.log) and [after](../evidence/M12/makako-manifest-check-after-gate.log) the gate. All live runs were on makako.sf.nethserver.net (Rocky Linux 9.8) with the M09 D13 timeouts.

After the gate, two source files changed. The [audited manifest](../evidence/M12/implementation-files-audited.sha256) differs from the verified manifest in exactly these files:
- **`scripts/demo_m12.py`:** the demonstration fixes described under "Demo attempts". The gate does not import the demo.
- **`.secrets.baseline`:** three demo env-check lines were audited as secret-scan false positives ([audit](../evidence/M12/secret-audit.md)).

`make check` on the audited source passed ([log](../evidence/M12/audited-check.log), [exit](../evidence/M12/audited-check-exit.txt)). This is the M11 precedent for demo-only changes after a gate. The demonstration ran on the audited source.

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check, run on makako | `make check`; [log](../evidence/M12/check.log), [exit](../evidence/M12/check-exit.txt) | PASS. On the laptop for the same revision: 904 passed, 119 skipped (gated cases). Ruff, format, mypy (341 files), secrets (1,453 files), baseline and profile checks passed. |
| M12-T01–T07, the D7 API checks, and the M01–M11 regression selection (119 cases) | `bash docs/evidence/M12/run-makako-gate.sh`. Evidence: [log](../evidence/M12/makako-live-integration.log), [JUnit](../evidence/M12/makako-live-junit.xml), [exit](../evidence/M12/makako-live-exit.txt), [host](../evidence/M12/makako-live-host-suspend.txt), [case check](../evidence/M12/makako-case-check.txt), [expected cases](../evidence/M12/regression-expected-cases.json) | PASS on attempt 2: 119 passed in 16,138 s (4:28:58). pytest, tee, restore and script all exited 0. Case check: 119 expected, 119 executed, none missing, extra or not passed. No host suspension. |
| Demonstration, no AI | `bash docs/evidence/M12/makako-run-demo.sh` (runs `scripts/demo_m12.py`); [env check](../evidence/M12/makako-demo-env-check.txt), [exit](../evidence/M12/makako-demo-exit.txt), [summary](../evidence/M12/demo/summary.json), screenshots in [`demo/`](../evidence/M12/demo/) | PASS on official attempt 4 (exit 0), with all six provider-key variables unset ([stderr, audit lines removed](../evidence/M12/makako-demo-stderr.log)). Earlier attempts are described below. |
| Accessibility | Recorded by T05: [keyboard and axe results](../evidence/M12/t05-accessibility.json) | PASS: 168 controls across 8 screens reached by Tab, each named and with a visible focus outline. axe-core 4.13.0 found 0 serious or critical WCAG 2.1 A/AA violations on 13 screens. |
| Static no-AI scan | [scan](../evidence/M12/no-ai-config-scan.txt) | PASS. No provider or model setting. The Explorer's only clients are the in-process API transport and the configured issuer. No script element in any template. |
| Dependency review | [review](../evidence/M12/dependencies.md), [artifacts](../evidence/M12/dependencies.json), [makako libraries](../evidence/M12/makako-chromium-deps.txt) | PASS. Runtime adds Jinja2 3.1.6 and MarkupSafe 3.0.4 (BSD-3-Clause). Test-only additions: Playwright 1.63.0 (Apache-2.0) and vendored axe-core 4.13.0 (MPL-2.0). |

### Per-check results (gate attempt 2)

| Check | Case time | Result |
|---|---|---|
| M12-T01 human/API parity | 244.8 s | PASS |
| M12-T02 no workspace detour | 482.9 s | PASS |
| M12-T03 hidden-data absence | 541.8 s | PASS |
| M12-T04 role enforcement | 198.8 s | PASS |
| M12-T05 safe presentation and keyboard | 360.1 s | PASS |
| M12-T06 evidence clarity | 516.0 s | PASS |
| M12-T07 revocation | 365.1 s | PASS |
| D7 API additions | 82.8 s | PASS |
| M01–M11 regression selection | 111 cases | PASS |

**Gate attempt 1 (not gate evidence; kept as [`makako-attempt1-*`](../evidence/M12/makako-attempt1-live-integration.log)).** It stopped at case 17 with 16 passed. It failed in M01-T03 (`test_t03_stale_base_and_lost_response`), during teardown: the M01 probe's OpenFGA SDK `DeleteStore` call came back `cancelled` on the client side, while the OpenFGA log shows the server healthy. M12 does not touch that probe code, and the same case passed in the M11 gate and again in attempt 2. Following the owner rule of full reruns over resume, the whole gate was rerun.

**Demo attempts.** Two trial runs outside the evidence script found two problems in the demo script: a full-page screenshot of a very tall page fails, and the renderer crashed screenshotting a 512 KiB context page on the memory-tight host. The demo now previews contexts at the API's default 64 KiB budget. The official runs through `makako-run-demo.sh`:

1. **Stopped by me (exit 143, SIGTERM).** The remote command outlived a local tool time limit. Its partial files were removed.
2. **Failed (exit 1)** after the A20 preview. The script then discarded stderr, so no traceback exists ([exit](../evidence/M12/makako-attempt2-demo-exit.txt), [env check](../evidence/M12/makako-attempt2-demo-env-check.txt)). Its empty stdout log was overwritten by attempt 3. Two changes followed: the script now keeps stderr without audit lines, and the demo allows 180 s per page action, because each page makes several 8–15 s API calls on makako.
3. **Failed (exit 1):** `Target crashed` while taking a full-page screenshot of the 50-item software lookup page ([stderr](../evidence/M12/makako-attempt3-demo-stderr.log), [exit](../evidence/M12/makako-attempt3-demo-exit.txt)). All screenshots are now viewport-only.
4. **Passed (exit 0).**

The partial screenshots of attempts 2 and 3 were not kept. These changes touch only `scripts/demo_m12.py` and `docs/evidence/M12/makako-run-demo.sh`. The gate imports neither.

## Demonstration

The demonstration ran in headless Chromium on disposable repositories, through the same `/v1` API that scripts use ([summary](../evidence/M12/demo/summary.json)):

1. **A02 reviewed write.** Carol lists the 3 directory entities without choosing a workspace, opens the shared Person and prepares a source-backed assertion (a Source, an Evidence item and the assertion) in forms. She submits it, and it validates. Dave opens it, approves and applies it: state `applied` ([Carol](../evidence/M12/demo/a02-carol-person.png), [Dave](../evidence/M12/demo/a02-dave-applied.png)).
2. **A14 scoped document.** The Handbook shows 3 parts to Alice and 5 to Bob, with no placeholder for the rest ([Alice](../evidence/M12/demo/a14-alice-document.png), [Bob](../evidence/M12/demo/a14-bob-document.png)).
3. **A15 cross-project context.** Dave previews `graph-context` anchored to Tesla with topic `batteries`. The outcome is `resolved`, and no project is selected ([screen](../evidence/M12/demo/a15-dave-context.png)).
4. **A18–A20 software contexts.** For an explicit target, Carol previews `test-development` and `support-documentation`, and Bob previews `documentation-update`. All three are `resolved`, and each page's outcome equals the API's ([A18](../evidence/M12/demo/a18-carol-test-development.png), [A19](../evidence/M12/demo/a19-carol-support-documentation.png), [A20](../evidence/M12/demo/a20-bob-documentation-update.png)).
5. **A21/A22 code labels.** Bob's software lookup labels code as `excerpt` or `complete-unit`, exactly as the API does ([screen](../evidence/M12/demo/a21-bob-lookup.png)).
6. **A22 reviewed widening.** Carol proposes moving Bob's draft into `sw-docs` with the Access form. Frank and Erin each find it in their Security operations list and approve it. The states go `proposed` → `proposed` (after Frank, destination admin) → `approved` (after Erin, lineage admin), and `applied` after Carol applies it ([screen](../evidence/M12/demo/a22-carol-applied.png)).

No AI provider variable was set, and no model, provider or AI configuration is involved.

## What was built

- **Composition (D1).** `c1.web.create_web_app` sends `/explorer` to a Starlette Explorer and everything else to the unchanged API. Operators can serve both with `uvicorn c1.web:from_env --factory`. The Explorer reaches C1 only through `ApiClient`: an in-process `httpx.ASGITransport` to the API app, carrying the person's own bearer token. A unit test enforces the import boundary.
- **Login and sessions (D2, D3).**
  - Keycloak client `c1-explorer` (confidential, PKCE S256) and its secret in the ignored `.env`.
  - `state`, nonce and a PKCE verifier per login; the ID token is validated only to finish login.
  - Server-side sessions with idle and absolute expiry; tokens never reach the browser.
  - `__Host-` cookies: the session cookie is `SameSite=Strict`, the login cookie `Lax`. A same-site continuation page completes login.
  - Logout ends both the C1 session and the identity-provider session.
- **Requests and rendering (D4, D5).**
  - Every state change requires `Origin`, a live session and the CSRF token before any API call.
  - Strict, size-limited form parsing.
  - `no-store`, a script-free CSP and related headers on every response.
  - Jinja2 autoescape and a closed widget set. No Markdown-to-HTML conversion. Links are generated only for C1 resource IRIs; other addresses are text.
- **Screens (D6).**
  - Reading: home, entities (M05 filters, project filter, cursor paging), resource detail with assertions about and referring to it, competing claims, neighborhood, history.
  - Documents: list, ordered authorized parts, Markdown and plain-text source, history.
  - Schema; context preview for every catalog profile (software target, goal, aspects, follow-up token, continuation); software target resolution and lookup.
  - ChangeSets: list, detail with operation preview, validation report and actions; forms for a new entity (two steps), aliases and keywords, a source-backed assertion, profile installation.
  - Access: your roles, scope creation and retirement, memberships, re-scope proposals, security-operation list and approval, instance grants.
- **API additions (D7).** `GET /v1/schema`, `GET /v1/access-scopes/mine` and `GET /v1/security-operations` ([API notes](M12-api.md)). `GET /v1/security-operations/{id}` is now also readable by lineage-scope admins, who may approve under M11 D7.
- **Hostile-hints profile (D11).** `example-hostile-hints` 1.0.0, an entity class whose `hint` enum carries script, image, `javascript:` and Markdown payloads plus a bidi control character.
- **Tests.**
  - `tests/unit/m12/`, 20 cases: login state, cookies, CSRF and origin, forms, sessions, 404/405 headers, escaping, import boundary, configuration, listings, the checkpoint fix.
  - `tests/browser/harness.py`: a real uvicorn server, Playwright, response capture, keyboard and axe helpers.
  - `tests/integration/m12/`: T01–T07 and the D7 checks.
- **Decision record.** [ADR-0023](../decisions/ADR-0023-explorer.md).

## Deviations and refinements

Recorded in [ADR-0023](../decisions/ADR-0023-explorer.md) where they are design choices.

- **Product defect found and fixed: truncated software contexts crashed.** A software-task context page that needed a continuation cursor raised `KeyError('topics')` in the shared checkpoint (`context/service.py`), so the API returned 500. Software interpretations have no topics, and M09–M11 tests always used the maximum budget. The checkpoint now treats a missing topic list as empty. A unit test and T07 cover it.
- **`Referrer-Policy: same-origin` instead of the planned `no-referrer`.** With `no-referrer`, Chromium sends `Origin: null` on same-origin form posts, which the D4 origin check must refuse. `same-origin` still never sends a referrer to another site.
- **Schema hints.** Profiles carry no labels or descriptions, and the shape loader rejects other SHACL predicates. The hostile hints are therefore property enum values, which the forms and schema page display. The loader was not changed.
- **Hostile class kind.** The class is of kind `entity`, so that the API lists it as an entity. The Explorer's create form likewise offers only core `Entity` and profile classes of kind `entity`.
- **`c1.model` is allowed in the Explorer.** It holds the record builders and keyword normalization: pure data, no I/O or authority. The plan had named only `c1.config`.
- **Missing CSRF token is 403.** It was planned as 403; the first implementation returned 400 until T04 caught it.
- **T07 continuation.** The plan expected the old continuation link to fail with `C1-CX-011` after the re-scope. When the moved file is not part of the first page's prefix, the API correctly accepts the continuation and builds the next page without the code. T07 accepts either outcome and always requires that the restricted code is absent.
- **T03 fixtures.** The document twin is M06's `omit_hidden_parts` load, plus a hidden relation whose UUID is the sentinel. The software twin is the existing template without `sw-restricted` records, and the restricted file's text is the sentinel. Pages are compared after removing only the CSRF token, revisions (including percent-encoded ones), instance IDs, ChangeSet IDs, recorded times and cursor tokens.
- **`scripts/api.py` is unchanged.** It is the M03 crash-test launcher with probe routes enabled. The Explorer is served by `c1.web:from_env` and by the test harness.
- **Entity form.** Without client script, creating an entity of a profile class takes two steps: choose the class, then fill that class's fields.

## Limitations and open items

- **Sessions** are per process and lost on restart (OD4). Production TLS and the deployment shape are M13 work.
- **Editing operations of an existing draft** (`PUT /v1/changesets/{id}/operations`) has no form. Users withdraw and recreate a draft; the API route is unchanged.
- **The Keycloak login page** is outside the accessibility audit.
- **Large context packages** (hundreds of KiB) produce very large pages. They work, but a full-page screenshot of one exceeded Chromium's limit on makako.
- **Security-operation listing** reads all journal operations per request. That is acceptable at fixture scale, like the M11 re-scope listing.
- **Browser cost.** The M12 cases add about 47 minutes to the makako gate.
- **Review.** One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

Plan M13 (release hardening and operational acceptance) against this report, if the owner authorizes it. No milestone starts automatically.
