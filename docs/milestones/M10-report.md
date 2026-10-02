# M10 — Documentation-first support context: execution report

**Gate:** VERIFIED

Approved plan: [M10](M10.md), plan commit `8d144dc`. Implementation authorized by the owner on 2026-10-01 ("proceed": implement M09a, then M10, then revalidate M11). Implementation revision: `8333091026b1ca087ad380e108fb91f45a77f12d`.

The milestone was verified on the 466-input source in [`implementation-files.sha256`](../evidence/M10/implementation-files.sha256). That file's own SHA-256 is `77accfefbaaade2a03e4f28c63bd457c95e41c498589f1851fd7251b21537cf7`. The manifest matched before and after the gate. After the gate, one demo evidence file was audited as a secret-scan false positive ([audit](../evidence/M10/secret-audit.md)). The [audited manifest](../evidence/M10/implementation-files-audited.sha256) differs only in `.secrets.baseline`, and `make check` on the audited source passed ([log](../evidence/M10/audited-check.log), [exit](../evidence/M10/audited-check-exit.txt)). The committed implementation revision contains exactly the audited source. All live runs were on makako.sf.nethserver.net (owner instruction "test on makako").

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check, run on makako | `make check`; [log](../evidence/M10/check.log), [exit](../evidence/M10/check-exit.txt) | PASS: 863 passed, 104 skipped. Ruff, format (467 files), mypy (303 files), secrets (1,307 files), baseline and profile checks all passed. |
| M10-T01–T06 plus the M01–M09a regression selection (104 cases) | `bash docs/evidence/M10/run-makako-gate.sh`. Evidence: [precheck](../evidence/M10/makako-manifest-check-before-gate.log), [log](../evidence/M10/makako-live-integration.log), [JUnit](../evidence/M10/makako-live-junit.xml), [exit](../evidence/M10/makako-live-exit.txt), [host](../evidence/M10/makako-live-host-suspend.txt), [case check](../evidence/M10/makako-case-check.txt), [post-check](../evidence/M10/makako-manifest-check-after-gate.log) | PASS (attempt 2): 104 passed in 11,777 s (3:16:17). pytest, tee, restore and script all exited 0. Case check: 104 expected, 104 executed, none missing, extra or not passed. |
| Two-request demonstration, no AI (A19) | `bash docs/evidence/M10/makako-run-demo.sh` (runs `scripts/demo_m10.py` on a disposable repository); [env check](../evidence/M10/makako-demo-env-check.txt), [result](../evidence/M10/makako-demo-result.json), [exit](../evidence/M10/makako-demo-exit.txt), [log](../evidence/M10/makako-demo.log) | PASS: demo exit 0; all six provider-key variables unset. The log keeps the audit lines; the result is extracted from it. |
| Static no-AI scan | [scan](../evidence/M10/no-ai-config-scan.txt) | PASS. `pyproject.toml`, `deployment/compose.yaml` and `.env.example` contain no provider or model setting. The new context modules import no network client. |

### Per-check results

| Check | Case time | Result |
|---|---|---|
| M10-T01 applicability before age | 16.4 s | PASS |
| M10-T02 focused fallback | 15.0 s | PASS |
| M10-T03 same target after newer ingestion | 59.2 s | PASS |
| M10-T04 evidence labels and warnings | 14.6 s | PASS |
| M10-T05 no privilege escalation (amended, below) | 97.9 s | PASS |
| M10-T06 no sufficiency oracle | 8.3 s | PASS |
| M01–M09a regression selection | 98 cases | PASS |

**Settings:** M09 D13 timeouts (budget 30,000 ms, backend 30 s, OpenFGA deadline 30 s). All provider-key variables were unset. Fixture: `software-integration` 1.2.0 (data only; the checked-in SCIP JSON is unchanged).

## Earlier gate attempt (not a pass)

| Attempt | Outcome | Cause and action |
|---|---|---|
| Aborted launch | `make check` failed on the baseline README inventory rule after the owner's upstream README rewrite (`0b9b944`), but the launch command still started the gate | Operator error: the launch did not test the `make check` exit code. The baseline rule was updated (below). The gate was stopped. |
| 1 (`makako-attempt1-*`) | 41 passed, then M03-T01 teardown got "authorization service unavailable" | The aborted gate had survived `pkill` and ran concurrently on the same stack. Its OpenFGA pause test left OpenFGA paused. Operator error, not an M10 defect. The orphan was force-killed, OpenFGA unpaused, and the M03 evidence file it had modified restored. Nothing was changed in the source. |
| **2** | **104 passed** | Gate of record. |

## Demonstration

The demonstration uses anchor `createInvoice`, target {a2, b2, `default`} and aspects [retry, timeout, configuration] ([result](../evidence/M10/makako-demo-result.json)). Both of Dave's stages ran at the same revision.

1. **Documentation stage (Dave).**
   - **Guidance:** the six parts of "Ledger operations guide 1.1", labelled official guidance.
   - **Warnings:** "Shop integration troubleshooting", the newest guide. It is declared `notApplicableTo` b2 and appears only as a warning with its evidence.
   - **Other-target documentation:** guide 1.0 and the a1/b1 `docs/invoicing.md`, as metadata without text.
   - **Missing aspects:** [Retry, Timeout] as "not addressed by the returned material". The response carries a signed follow-up token.
2. **Implementation stage (Dave).** It used the token and the missing aspects, and was explicitly requested; C1 does not run it on its own. It returned:
   - **Implementation:** a2 `ledger.api.create_invoice` and b2 `shop.ledger_client.post_invoice`, the two retry-addressing symbols. It also returned `create_invoice`'s direct same-snapshot dependencies: `Invoice`, `validate`, `InvalidAmount` and `store.save`. All code is labelled "implementation evidence, not a supported procedure".
   - **Interfaces:** the linked interface operation.
   - **Observed tests:** three labelled test runs.
   - **Interpretations:** the two analyzer `addressesAspect` claims.
   - **Missing aspects:** [Timeout].
3. **Alice (`sw-shared` only).** She gets the uniform 404 `C1-SW-404`, because she cannot read the target snapshots (see the T05 amendment below).

Every package states: "Prepared for the requesting principal; read access is not publication permission." 

## Deviations and refinements

These are recorded in [ADR-0021](../decisions/ADR-0021-support-contexts.md).

- **D1, section templates.** The documentation template has no separate configuration or limitations sections. Each guidance part lists the aspects it addresses, so the guide's configuration section addresses `configuration`.
- **D9 and M10-T05, owner decision (2026-10-02).** The target snapshots live in repository scopes. Alice, who reads only `sw-shared`, therefore cannot resolve the target, and both support stages give her the uniform target not-found (404 `C1-SW-404`). That follows the M08/M09 rule that hidden and missing targets answer identically. The plan assumed Alice would receive a package listing [retry] as missing. The owner kept the 404 ("Keep 404; amend T05"). T05 now proves:
  - Alice's 404 bodies are identical for both stages and for an unknown snapshot;
  - they are unchanged on a copy with extra hidden retry-addressing code, which Dave can see;
  - a code-part citation is the same 404 as an unknown ID.

  The demo shows Alice's 404 instead of an implementation package.
- **Unit tests.** Planned unit coverage of follow-up token binding and the label template is provided by the live T03 and T04 tests, not by separate unit tests. The unit tests cover applicability ordering, missing aspects, aspect resolution, the per-task grammar and the request digest.
- **Earlier tests updated (data only).** Guides carry a `guide:` content revision instead of a commit. M08-T02 and M09-T01 accept that revision kind. M08-T02's expected document set gains the 1.0 guide. M09-T02 selects its discrepancy by normative part. The M09 unit digest reference excludes `aspects` and `followup_token` when they are absent.
- **Baseline README rule (outside M10 scope, needed for the gate).** The owner's README rewrite uses bold inventory labels and lists the M04–M09 capabilities. `scripts/check_baseline.py` now accepts plain or bold labels and the verified M04–M09 capability names. A new negative test proves that an unlisted capability still fails.

## Limitations and open items

- **Documentation-only readers cannot pin a target.** Reading pinned target metadata without repository read access needs a later milestone or an owner decision (ADR-0021 amendment).
- **Aspects are declared only.** There is no inference from text or names, by design. A guide or code unit addresses an aspect only through an attributed `addressesAspect` claim.
- **Negative applicability is one predicate.** `notApplicableTo` is the minimal form; M11 must map it onto, or preserve it alongside, its applicability states.
- **Request cost.** Each support request takes about 8–15 s on makako with the M09a costs; ChangeSet decisions are still per resource (M09a open item).
- **Review.** One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

Revalidate the M11 plan against this report, then ask the owner before implementing M11.
