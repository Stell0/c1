# ADR-0021 — Documentation-first support contexts

**Status:** Accepted for M10 implementation, 2026-10-01.
**Context:** [M10 plan](../milestones/M10.md) D1–D10; ADR-0018 (software-task context profiles); spec §10.2, §10.5, §11.2–11.3, A19.

## Decision

1. **Two profiles.** `support-documentation` 1 and `support-implementation` 1 are software-task profiles. Each task has a fixed section template and a fixed set of unit kinds whose evidence roles must all be declared:
   - **`support-documentation`:** sections guidance, warnings, other-target documentation and missing aspects.
   - **`support-implementation`:** sections implementation, configuration, interfaces, observed tests, interpretations and missing aspects.

   Only `test-development` takes a `goal`; a support request with a goal is rejected. `support-implementation` requires `aspects`.
2. **Declared exact aspects.** `software` profile 1.2.0 adds:
   - the entity class `Aspect`;
   - `addressesAspect` (from a DocumentPart, CodeSymbol, TestCase or Configuration);
   - `notApplicableTo` (a Document to a SourceSnapshot).

   Requests name aspects by ID or by exact normalized label; there is no stemming or synonym expansion. Unknown and hidden aspects both report `unresolved`.
3. **Applicability before age.** A documentation-stage candidate documents the anchor or carries a part that addresses a requested aspect. A candidate with a readable `notApplicableTo` to a target snapshot appears only as a warning, with its evidence. A candidate with a readable `describesSnapshot` to a target snapshot is guidance. A candidate that documents the anchor but describes only other snapshots is listed as metadata without text. Guidance is ordered by best review state, then by `dcterms:issued` descending, then by ID. Recorded discrepancies that touch a guidance part are warnings.
4. **Missing aspects.** A requested aspect is reported "not addressed by the returned material" when no returned unit addresses it: a guidance part, or a code symbol's or configuration's aspect claim. Nothing is said about material outside the response.
5. **Follow-up token.** The documentation stage returns `followup` with the revision, the resolved target, the missing aspects and a signed token. The token is made by the M05 cursor codec, with order `support-followup`. It binds the principal, the revision, the anchor and target selectors, and the profile pair. The implementation stage uses the token's revision. Another principal, a different anchor or target, or a conflicting `revision` gives 400 `C1-CX-001`. C1 never runs the second stage itself.
6. **Focused implementation.** Code is selected only from readable `addressesAspect` claims on CodeSymbols that are pinned at a target commit. Selected code includes the definitions at the target and their direct same-snapshot dependencies (the M09 rule). Interfaces linked from those symbols and the labelled runs of test cases verifying those interfaces are also included. Aspect claims are listed as attributed interpretations.
7. **Labels.** Guidance parts are labelled "official guidance" (normative); code and configuration are labelled "implementation evidence, not a supported procedure" (structural). Every package states that read access is not publication permission.

*Refinement of plan D1:* the documentation template has no separate configuration or limitations sections. Each guidance part lists the aspects it addresses; for example, the guide's configuration section addresses `configuration`.

## Consequences

- **Fixture v1.2:** published guides in `sw-shared`, aspects, analyzer aspect claims on a2 `create_invoice` and b2 `post_invoice`, and a second review note that links a1 `validate` to the 1.0 guide's limitation.
- **Earlier tests updated:** guides are documentation that applies to targets but carries a `guide:` content revision instead of a commit. M08-T02 and M09-T01 accept that revision kind. M08-T02's expected document set gains the 1.0 guide, and M09-T02 selects its discrepancy by normative part.
- **Development databases:** databases that installed `software` 1.1.0 must be reinstalled; there are no migrations, per the owner.

## Rejected alternatives

- **Inferring aspects from text or names.** Rejected as nondeterministic, and it would be a sufficiency judgment.
- **An automatic second stage.** Rejected: the spec forbids autonomous fallback.

## Amendment (owner decision, 2026-10-02): target visibility for documentation-only readers

In the fixture, the target snapshots live in repository scopes. A documentation-only reader, Alice with `sw-shared` only, therefore cannot resolve a target. Both support stages give her the uniform target not-found answer (404 `C1-SW-404`): the M08/M09 rule that hidden and missing targets answer identically.

Plan D9 assumed Alice would receive an implementation package listing the requested aspects as missing. The owner kept the uniform 404 rather than publishing snapshot metadata or adding a new reader scope. M10-T05 now checks the following:
- the 404 bodies are identical for both stages and for an unknown snapshot;
- they stay identical on a copy with extra hidden retry code;
- code-part citations remain 404.

Reading pinned targets without reading repository content is left open for a later milestone or owner decision.
