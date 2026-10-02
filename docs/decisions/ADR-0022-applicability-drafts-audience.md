# ADR-0022 — Applicability, documentation drafts and audience widening

**Status:** Accepted for M11 implementation, 2026-10-02.
**Context:** [M11 plan](../milestones/M11.md) D1–D9 and §1a; ADR-0009 (current bindings); ADR-0010 (security operations); ADR-0018 (software-task profiles); ADR-0021 (support contexts); spec §10.5, §11.4, A20, A22.

## Decision

1. **Applicability records.** `software` profile 1.3.0 adds four record classes:

   | Class | Contents |
   |---|---|
   | `ApplicabilityCheck` | One rule run over an exact target: rule, target snapshots and contracts, `checkedAt`, activity. |
   | `ApplicabilityRecord` | Subject (a Document or DocumentPart), target snapshots, state (`applicable`, `needs-review`, `not-applicable` or `contradicted`), basis (`declared`, `rule`, `review` or `test`), optional rule and check, activity, cited evidence parts and digests, note, review status. |
   | `DocumentationDraft` | The draft record; see item 4. |
   | `ExternalPublication` | The publication receipt; see item 6. |

   Part-to-part lineage uses `prov:wasDerivedFrom` as an assertion predicate with range DocumentPart. The earlier declarations stay as they are and are read as inputs: `describesSnapshot` counts as `applicable` (declared, document level), and `notApplicableTo` as `not-applicable` (declared).

2. **Effective state.** For each part and target snapshot:
   - part-level inputs decide over document-level inputs;
   - within a level the most cautious state wins: `contradicted`, then `not-applicable`, then `needs-review`, then `applicable`;
   - with no readable input the state is `unknown`.

   Every contributing readable record is listed with the level that decided. A document is never marked obsolete globally.

3. **External rule `doc-dependency-change/1`** (`scripts/doc_review_rule.py`).
   - **Where it runs:** as the analyzer producer, over the producer's own checked-in inputs.
   - **What it compares:** for a part that declares `documents` for an operation, it compares the part's described snapshot with each target snapshot in the same repository, on two digests:
     - the operation's object in the contract (canonical digest);
     - the definition part of the operation's declared handler (text digest).
   - **What it records:** a difference yields `needs-review` (basis `rule`), citing the compared parts and their digests. The rule never writes `contradicted`. Every run records one `ApplicabilityCheck`.
   - **C1's role:** none; C1 runs no analysis.

4. **Drafts.**
   - **Shape:** a draft is a core Document with ordered parts plus a `DocumentationDraft` record (document, `revises`, target snapshots and contract, author, state, applicability check). The record inherits the Document's binding.
   - **Lineage:** lineage assertions are bound to the drafting scope itself, not inherited, so widening the draft never moves lineage to a broader audience.
   - **ChangeSet validation rules:**
     - **`C1-CS-051` (`draft_requires_drafting_scope`):** a new draft, or a Document it names, outside a scope of kind `drafting`.
     - **`C1-CS-050` (`applicability_revalidation_required`):** an `approved` draft whose check does not cover exactly its target, or is not the latest readable check of that rule for that target.

5. **Drafting scopes and lineage-aware widening.**
   - **Drafting scopes:** a scope has a fixed `kind`, either `standard` or `drafting`.
   - **Required approvals:** a re-scope whose cascade holds a draft resource records, at proposal, the lineage source parts, their current scopes and a digest. It then needs independent approvals that together administer the destination and every lineage scope. Each approval counts only for scopes its approver administers at check time, and the proposer never counts.
   - **Fail-closed checks:** an unreadable, transitioning or pending lineage source refuses the proposal with 409 `lineage_unavailable`. A changed lineage at apply refuses with 409 `stale_security_operation`.
   - **Non-draft re-scopes:** they keep the M03 rule, destination only.

6. **Publication receipts.**
   - **Who creates them:** an `ExternalPublication` is created only through an ordinary ChangeSet by a producer with creation rights in the receipt scope; in the fixture that is `c1-svc-ci` in `sw-publications`.
   - **Rejection rule:** a receipt created in a drafting scope is rejected (`C1-CS-052`).
   - **Publication state:** a draft's publication state is derived only from readable receipts.
   - **Locators:** they are inert text and are never fetched.

7. **`documentation-update` profile** (software-task kind).
   - **Request:** the anchor is a capability or operation. The target must name snapshots of at least two repositories (otherwise 400 `C1-CX-001`). `goal`, `aspects` and `followup_token` are rejected.
   - **Sections, in order:** interpretation, target, document structure, responsibilities, interface contract, configuration, tests and runs, changes, drafts, compatibility, gaps, sources, bounds.
   - **Compatibility:** for each cross-repository pair it is `unknown` unless a matching live run covers exactly that pair.

## Refinements of the plan

- **Error codes.** `C1-CS-020` already labels the competing-claims diagnostic, so the plan's `C1-CS-020` and `C1-CS-021` became `C1-CS-050` and `C1-CS-051`. The receipt rule adds `C1-CS-052`.
- **Rule baseline (D3).** The a2 copy of `docs/invoicing.md` carries no declarations; only the a1 copy describes a1 and b1. The rule therefore compares the described snapshot a1 with the target a2. At {a2, b2}, "Reading an invoice" is `unknown`, not "applicable by declaration" as the plan expected. No applicability is inferred from unchanged dependencies.
- **Drafts section.** The template adds a drafts section, so draft lineage and publication state are visible in the package (T04, T05, T07).
- **Draft lineage source (D9, T07).** The draft cites the a2 contract part, a2 `create_invoice` and b2 `shop.client.submit_order`, the declared caller of `createInvoice`. T07 re-scopes b2 `shop/client.py`, so the change reaches both the package and the lineage.
- **Fixture drafts.** Drafts and receipts are created by the tests and the demo, not by the template load, so the tests can observe each state transition.
- **Widening destination.** The widening goes to `sw-docs` (owner decision, M11 §1a item 6).

## Consequences

- **Fixture v1.3:**
  - part-level `documents` claims on the a1 invoicing guide;
  - one rule run for {a2, b2, contract 1.1.0};
  - the scopes `drafts-bob` (drafting), `sw-docs` (created by Frank) and `sw-publications` (ci only);
  - Bob's grants and the extra roles.
- **Development databases:** databases holding `software` 1.2.0 must be reinstalled.
- **Re-scope cost:** every re-scope proposal and apply makes one typed listing of draft records. A draft re-scope also lists assertions to find lineage.
- **M10 support contexts:** they still read only declarations, not `ApplicabilityRecord`s.

## Rejected alternatives

- **"Most restrictive scope" for drafts.** Forbidden by AGENTS.md §5.3. Lineage coverage is set coverage.
- **Inheriting lineage assertions into the widened scope.** Rejected because it would expose hidden source identifiers to the wider audience.
- **Having the rule write `applicable` for unchanged dependencies.** Rejected: unchanged dependencies are not proof of applicability.
