# M07 final acceptance review

Review date: 2026-09-28. Reviewer: independent delegated architecture/security
advisor. Scope: the M07 contract in `PLAN.md` and `docs/milestones/M07.md`, the
seven integration tests and their helpers, retained corrected execution
evidence, and focused source/unit-test coverage of previously reported issues.
Only this review document was written during this review.

## Outcome and evidence boundary

No unresolved M07 feature/security blocker was identified in this bounded
review. The corrected execution evidence supports **T01–T07 PASS**, but this
review does **not** declare the overall milestone VERIFIED. The earlier-milestone
regressions and final runtime/probe/cleanup checks remain pending at this
handoff, and their results must be incorporated by the milestone lead.

The reviewer inspected, rather than independently executed, the following:

- [Corrected JUnit](m07-corrected-junit.xml): exactly seven named M07 cases,
  zero failures, errors, or skips; suite time 5592.028 seconds.
- [Corrected log](m07-integration-corrected.log) and
  [exit record](m07-corrected-exit.txt): seven passed in 5592.03 seconds,
  process exit 0.
- [Post-gate manifest check](manifest-check-after-m07.log): 339 frozen
  implementation inputs unchanged. The reviewer additionally executed
  `sha256sum --check --quiet docs/evidence/M07/implementation-files.sha256`
  during this review; it returned exit 0. This was a file-integrity check, not
  a test or service call.
- [Final local check log](check-final-gate.log): Ruff and formatting checks,
  mypy for 238 source files, 630 pytest passes with 79 real-service skips,
  secret scan, baseline check, and profile generation check. These local
  results do not replace the real-service gate or pending earlier regressions.

The [first failed run](m07-first-junit.xml) remains valid historical evidence;
the corrected result does not erase its T01/T03/T07 timeout failures. See
[performance review](performance-review.md) for the intervening bounded fixes
and their security assumptions.

## Contract-to-test assessment

| Contract | Actual assertion coverage inspected | Assessment |
| --- | --- | --- |
| T01 cross-project reuse/no AI | The API loader uses both authenticated service producers and independent review. Robotelier explicitly resolves the one existing Tesla ID before its ChangeSet. The test asserts one readable Tesla, no project selector, absent provider-key variables, all three public battery labels, populated text/citations, and reviewed Markdown/JSON goldens. It also checks unauthenticated rejection and invalid profile-group/storage-ID writes. | Covered by corrected T01 execution. |
| T02 graph versus exact keywords | M-B3 appears with the Tesla/Megapack/component path; exact ALL returns only V-B2; unrelated solar/instrument IDs are absent; controlled alternative topic labels produce the same topic and facts. | Covered by corrected T02 execution. |
| T03 authorized selection | Dave's complete response is scanned for protected battery/product/part IDs, labels, title, and excerpt token; Carol sees them and the hidden part resource read differs 404/200. Adding a hidden topic assertion between readable resources leaves the canonical public response unchanged at the new content head. | Covered by corrected T03 execution; focused unit tests additionally isolate hidden path edges, topic carriers, and endpoints. |
| T04 evidence integrity | Both M-B3 values survive with separate sources, linked measurements, units/conditions, known validity and declared disagreement. O-B1 has one original source and two explicit import activities, marked duplicate import. V-B2's missing unit is explicit; product/version roles and quantities remain separate. | Covered by corrected T04 execution; negative comparison cases are covered by unit tests. |
| T05 usable payload/parity | Every claim has a value and citations; returned evidence/source/part/document/selector IDs resolve through authorized resource APIs. Escaped excerpts, per-unit citation numbers, source footnotes, and parity digest agree with Markdown. T01 goldens cover the full selected qualifications. | Covered by corrected T05 execution. Escaping is intentional; raw producer text is not inserted as executable Markdown. |
| T06 deterministic bounded units | Same-revision requests match after declared volatility normalization. A measured boundary yields exactly two whole units, preserved caveats/conflicts and explicit continuation; concatenated pages equal full facts. An insufficient budget returns 422 with a larger minimum. | Covered by corrected T06 execution, supplemented by actual UTF-8 byte-count and longest-prefix unit tests. |
| T07 ambiguity/revocation/gaps | Two readable Tesla candidates remain ambiguous; a hidden third candidate is excluded. Explicit ID resolves, an unknown topic remains unresolved, and missing-field language is limited to returned material. Revoking Dave's scope between pages rejects continuation with C1-CX-011; a fresh request omits the revoked units. | Covered by corrected T07 execution. |

Goldens retain real producer attribution: expected producer placeholders are
bound to the authenticated fixture principals. Normalization removes declared
request/time/repository-revision volatility; it does not remove qualifications,
source revisions, source identity, excerpts, or producer identity from actual
packages.

## Previous findings and targeted coverage

- **Independent authorization of references and paths:**
  `test_topic_references.py` checks scheme pruning on list/detail/export and
  generic resource reads, plus authorized references on writes.
  `test_selection.py` checks ordered typed paths, hidden relationships and
  topic carriers, and expansion through readable broader assertions only.
- **Measurement isolation and conservative conflict classification:**
  `test_units.py` checks independently readable measurement links/qualifiers,
  wrong or ambiguous measurement targets, missing qualifiers, incomparable
  conditions, unknown/disjoint validity, and multi-valued predicates. Source
  revisions remain distinct metadata but do not inflate original-source counts;
  automatic apply activities are not counted as source imports.
- **DocumentPart citation integrity:** the unit tests require the complete
  independently readable document/part/source-link/source chain, correct
  selector and revision association, and reject old evidence against edited
  document/part content. Producer excerpts cannot bypass hidden dependencies.
  Source version and document/evidence version remain separate.
- **Determinism, rendering and budgets:** canonical label/type ordering,
  escaped hostile content, safe code excerpts, global citation numbers,
  whole disagreement/qualification units, actual emitted UTF-8 size, cursor
  alphabet/size handling, and nonadvancing-page rejection have targeted tests.
  The live T06 test checks reported byte bounds; the independent comparison to
  `len(markdown.encode("utf-8"))` on every constructed page is in unit tests.
- **Continuation authority:** `test_service.py` checks prefix-content and used
  binding changes while excluding unrelated bindings; selection/unit tests
  retain authorized anchor/topic/matching dependencies. The service reselects
  with current authority, validates the signed prefix checkpoint, and finalizes
  the original plan before returning either resolved or ambiguous material.
  Live T07 supplies the actual revoked-membership continuation case.
- **Necessary write-path repairs:** T01 exercises rejection of multiple profile
  installations and unrepresentable canonical IDs before knowledge mutation.
  The narrower legacy-read/recovery/idempotency conditions have dedicated unit
  coverage and earlier review; uncertain apply outcomes are not claimed safe
  merely from the context tests.
- **Performance/security preservation:** the reviewed overlaps retain fresh
  authorization and current binding checks, exact-head guards, original
  deadlines, bounded backend reads, and awaited cancellation. Corrected live
  success is evidence for the tested environment, not a general latency SLA.

## Remaining closure work and limits

No new implementation change is requested by this review. Final closure still
requires the pending earlier regressions, final operational checks, and the
milestone lead's final report/status decision. At review time the evidence index
and milestone-plan status prose still described the corrected run as incomplete;
update those descriptions to the retained terminal result without deleting
prior failures or claiming the pending checks have passed.

The seven live cases are a bounded synthetic acceptance suite. They do not
individually inject every hidden qualifier, citation-revision mismatch, or
binding movement; those specific negative cases are covered by the inspected
unit tests and earlier regressions. This review did not rerun tests, contact
services, alter permissions, or independently reproduce the reported latency.
