# M11 — Cross-software documentation-update context: execution report

**Gate:** VERIFIED

Approved plan: [M11](M11.md), revalidated against the M10 report (§1a, commit `51cfd40`). The owner chose the approver arrangement ("New sw-docs scope") and authorized implementation on 2026-10-02 ("Implement M11"); see commit `e73d5ae`. Implementation revision: `67619e3817bfe6831f70d20c60024047ed1558ce`.

The milestone was verified on the 481-input source in [`implementation-files.sha256`](../evidence/M11/implementation-files.sha256). That file's own SHA-256 is `53ce810fadaf461d554db6cb57fde45c7632b3d243d8b2e399df1d5fb5090aa2`. The manifest matched before and after the gate. All live runs were on makako.sf.nethserver.net (owner instruction "test on makako").

After the gate, two changes were made to the source; the [audited manifest](../evidence/M11/implementation-files-audited.sha256) differs from the verified manifest only in these two files:
- **`.secrets.baseline`:** two demo env-check lines were audited as secret-scan false positives ([audit](../evidence/M11/secret-audit.md)).
- **`scripts/demo_m11.py`:** the demo was reordered so that Bob approves his draft before it is widened. The gate does not import the demo.

`make check` on the audited source passed ([log](../evidence/M11/audited-check.log), [exit](../evidence/M11/audited-check-exit.txt)). The committed implementation revision contains exactly the audited source.

## Named checks

| Check | Command and evidence | Result |
|---|---|---|
| Local check, run on makako | `make check`; [log](../evidence/M11/check.log), [exit](../evidence/M11/check-exit.txt) | PASS: 884 passed, 111 skipped (gated source). Ruff, format (486 files), mypy (317 files), secrets (1,357 files), baseline and profile checks all passed. |
| M11-T01–T07 plus the M01–M10 regression selection (111 cases) | `bash docs/evidence/M11/run-makako-gate.sh`. Evidence: [precheck](../evidence/M11/makako-manifest-check-before-gate.log), [log](../evidence/M11/makako-live-integration.log), [JUnit](../evidence/M11/makako-live-junit.xml), [exit](../evidence/M11/makako-live-exit.txt), [host](../evidence/M11/makako-live-host-suspend.txt), [case check](../evidence/M11/makako-case-check.txt), [post-check](../evidence/M11/makako-manifest-check-after-gate.log) | PASS (attempt 1): 111 passed in 12,834 s (3:33:53). pytest, tee, restore and script all exited 0. Case check: 111 expected, 111 executed, none missing, extra or not passed. |
| A20 demonstration, no AI | `bash docs/evidence/M11/makako-run-demo.sh` (runs `scripts/demo_m11.py` on a disposable repository); [env check](../evidence/M11/makako-demo-env-check.txt), [result](../evidence/M11/makako-demo-result.json), [exit](../evidence/M11/makako-demo-exit.txt), [log](../evidence/M11/makako-demo.log) | PASS on attempt 2: demo exit 0, with all six provider-key variables unset. Attempt 1 ([log](../evidence/M11/makako-attempt1-demo.log)) exited 1. It widened the draft before approving it, so Bob's later edit of the widened draft was correctly denied, because Bob does not contribute in `sw-docs`. The demo was reordered to match T05. |
| Static no-AI scan | [scan](../evidence/M11/no-ai-config-scan.txt) | PASS. There is no provider or model setting, and the new context and rule modules import no network client. |

### Per-check results

| Check | Case time | Result |
|---|---|---|
| M11-T01 both sides of the feature | 34.7 s | PASS |
| M11-T02 relative obsolescence | 83.4 s | PASS |
| M11-T03 review candidate, not proof | 68.7 s | PASS |
| M11-T04 draft lineage | 145.8 s | PASS |
| M11-T05 separate publication | 245.6 s | PASS |
| M11-T06 audience and freshness | 296.0 s | PASS |
| M11-T07 historical protection | 260.9 s | PASS |
| M01–M10 regression selection | 104 cases | PASS |

**Settings:** M09 D13 timeouts (budget 30,000 ms, backend 30 s, OpenFGA deadline 30 s). All provider-key variables were unset. Fixture: `software-integration` 1.3.0, whose checked-in repositories and SCIP JSON are unchanged.

**Development runs before the gate (not gate evidence).** Two earlier runs of `tests/integration/m11` failed: 7 failures, then 2.
- **Product defect, fixed:** an ordering key compared ints with strings across unit kinds.
- **Test-helper defects, fixed:**
  - the helper called `validate` after `submit`, which already validates;
  - three expectations were wrong: `submit_order` also implements the capability; `shop.client.validate` is a legitimate direct dependency; the Markdown escapes dots in the locator.
- **Fixture correction:** the publisher must read the widened scope, and the draft must be widened before publication. These are fixture grants (`ci` and Bob read `sw-docs`); no security rule changed.

## Demonstration

The demonstration uses capability "Invoice creation", target {a2, b2, contract 1.1.0, `default`}, and Bob as the reader ([result](../evidence/M11/makako-demo-result.json)).

1. **Update context.** Bob's package has these sections:
   - **Document structure:**
     - "Ledger operations guide 1.1" is applicable at a2.
     - The a1 `docs/invoicing.md` has "Creating an invoice" as `needs-review` at a2 (rule) and "Reading an invoice" as `unknown`.
     - The troubleshooting guide is `unknown` at a2 and `not-applicable` at b2.
     - Guide 1.0 is listed as other-target metadata, without text.
   - **Responsibilities:** ledger `create_invoice` (implements the operation and the capability) and shop `submit_order` (declared call, implements the capability).
   - **Interface contract:** the 1.1.0 contract part and `createInvoice` with both links.
   - **Changes:** two rule review candidates and the M09 discrepancy.
   - **Compatibility:** a2–b2 is `unknown`.
   - **Publication statement:** present.
2. **Draft.** Bob submits "Invoicing (1.1)" with lineage into `drafts-bob`; Dave reviews it. Bob then approves the draft through a reviewed ChangeSet: the draft is `approved` and `not-published`.
3. **Widening.** Carol proposes `sw-docs`. The operation stays `proposed` after Frank's approval and becomes `approved` after Erin's; Carol then applies it.
4. **Publication.** The `ci` publisher imports a receipt, and the draft's publication state becomes `published`.
5. **Alice.** Alice reads the widened draft (200) and nothing of its lineage, as T07 shows.

## Deviations and refinements

These are recorded in [ADR-0022](../decisions/ADR-0022-applicability-drafts-audience.md).

- **Error codes.** `C1-CS-020` already labels the competing-claims diagnostic, so the plan's draft codes became `C1-CS-050` (`applicability_revalidation_required`) and `C1-CS-051` (`draft_requires_drafting_scope`). The receipt rule adds `C1-CS-052`.
- **Rule baseline and T02.** In the fixture only the a1 copy of `docs/invoicing.md` carries declarations, describing a1 and b1. The rule therefore compares a1 with the target a2. At {a2, b2}, "Creating an invoice" is `needs-review` (rule) and "Reading an invoice" is `unknown`. The plan expected "applicable by declaration", but no declaration covers a2, and the rule does not infer applicability from unchanged dependencies.
- **Drafts section.** The template adds a `drafts` section, which shows each draft's lineage and its publication state.
- **Lineage stays quarantined.** Lineage assertions are bound to `drafts-bob` and are not inherited, so widening never moves lineage to a broader audience.
- **Lineage source and T07.** The draft cites b2 `shop.client.submit_order`, the declared caller. The plan named `post_invoice`, which does not call `createInvoice`. T07 re-scopes b2 `shop/client.py`.
- **Publication follows widening.** The publisher (`ci`) reads `sw-docs`, never the drafting scope, so T05 widens the draft before the receipt is imported.
- **Draft creation.** Drafts and receipts are created by the tests and the demo, not by the template load.
- **Re-scope approval.** Approval now counts each independent approver for the scopes they administer. A re-scope without draft lineage keeps the M03 rule (destination only).

## Limitations and open items

- **The rule covers interface operations only.** It compares contract operation objects and declared handlers; capability-level `documents` claims are not compared.
- **Compatibility evidence is narrow.** It comes only from matching live runs; contract-level compatibility is not computed.
- **M10 support contexts** still read only declarations, not applicability records.
- **Re-scope cost.** Every re-scope proposal lists draft records, and a draft re-scope also lists all assertions to find lineage. This is acceptable at fixture scale but not indexed.
- **Draft quarantine is enforced by scope kind only.** That a drafting scope's only readers are the author and reviewers is a fixture arrangement; C1 does not check membership.
- **Review.** One agent implemented and reviewed this milestone; there was no independent human review.

## Next bounded action

Plan M12 (Human Explorer) against this report, if the owner authorizes it. No milestone starts automatically.
