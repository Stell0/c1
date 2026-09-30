# ADR-0018 — Software-task context profiles: test development

**Status:** Accepted for M09 implementation, 2026-09-29.
**Context:** [M09 plan](../milestones/M09.md) D1–D11 and its §1a revalidation; ADR-0016 (M07 context packages); ADR-0017 (software profile); PROJECT_SPECIFICATION.md §10.4, §11.1, §11.5; AGENTS.md §6.2 and §7.

## Decision

1. **A second context-profile kind.** The trusted local catalog accepts a
   software-task profile. It is recognized by its `software` block and
   validated by its own closed model. The M07 graph profile model and its
   digests are unchanged. A software-task profile declares:
   - the task (`test-development`);
   - its anchor kinds;
   - bounded dependency, test and run limits;
   - an evidence role for every unit kind;
   - the fixed section template.

   It has no free text, templates or executable fields.
2. **Request grammar.** `/v1/context` gains two optional fields:
   - `target`: a target-set ID, or inline snapshots, contracts and
     configurations. Branch names are resolved only by
     `/v1/software/targets/resolve`.
   - `goal`: `conformance` or `characterization`.

   A software-task profile requires both and rejects topics, keywords,
   fields and `project_ref`. A graph profile rejects both with
   `C1-CX-001`. The continuation digest covers `target` and `goal` only
   when they are present, so M07 request digests are unchanged.
3. **One authorized selection.** The selection stage reads only the
   request's authorized records and the target resolved from them, with the
   same M08 class and pinning rules. It proceeds in fixed order:
   1. target definitions;
   2. direct same-snapshot dependencies, through reference occurrences
      inside the definition part;
   3. interfaces (`implementsOperation` and `declaredCall` pinned at a
      target commit);
   4. normative documentation (`documents` plus `describesSnapshot` of a
      target snapshot) and the target's contract Document;
   5. test cases (`verifies` of the anchor, symbols, operations or
      implemented capabilities, or a definition referencing a target
      symbol);
   6. their runs;
   7. `fixtureOf` fixtures;
   8. `executionInstructions` sections;
   9. `discrepancy` assertions touching a selected part.

   Each unit is one stored part or one record, is indivisible, and is
   budgeted by the M07 whole-unit rule.
4. **Evidence roles and goals.** Every unit carries the role that the
   profile maps from its kind:
   - normative;
   - structural;
   - interpretive;
   - observed;
   - instruction, for untrusted execution text, which is always fenced as
     text.

   The goal changes only the header statement and two section labels,
   never the selection.
5. **Run labels.** A run *matches* only when all of its snapshots are target
   snapshots and its configuration is a target configuration, or both are
   absent. Otherwise it is `other-target`. A run is `integration evidence`
   only if it matches, is live, and covers target snapshots of at least two
   repositories. A test case without a matching run is `definition-only`.
6. **Completeness and gaps.** Code units carry `code_completeness` from the
   stored `partKind`, and the Markdown fence info says `complete unit` or
   `excerpt`. Every package carries the same fixed statement that
   referenced definitions not listed are not included. Readable
   `UnresolvedReference` and `ImportIssue` records for returned code files
   are listed with their reasons. Nothing depends on whether a hidden
   dependency exists.
7. **Vocabulary.** The `software` profile moves to 1.1.0. It adds three
   relationship predicates, each with a class range:
   - `executionInstructions`: Document to CodeRepository;
   - `fixtureOf`: CodeSymbol to TestCase;
   - `discrepancy`: implementation DocumentPart to normative DocumentPart.

   The owner stated that there are no production installs and migrations
   need not be handled, so the profile is extended in place rather than
   adding a separately named profile.

## Consequences

- **Configurable backend timeouts (plan D13).** The OpenFGA/OIDC client timeouts (`C1_BACKEND_TIMEOUT_S`, default 5 s) and the OpenFGA server deadlines (`C1_FGA_DEADLINE`, default `3s`) can be raised on slow hosts. Their defaults are unchanged.

- **Request budget (plan D12, owner-approved 2026-09-30).** The default request budget is now 10,000 ms; it was 5,000 ms under M07 D22. The cap stays at 30,000 ms, and exceeding the budget still fails closed. The reason is the M05 per-resource binding re-verification, which takes about 3.5 s per request at this fixture's size.

- The M07 `unit_citations` helper also reads a unit's own `citations` list,
  and `build_page` accepts the two renderers as parameters. Graph packages
  are unchanged.
- Development databases that installed `software` 1.0.0 must be reset. There
  is no upgrade path, as before (M08 plan, Conflict 2).
- The external consumer runs only checked-in fixture sources and the
  checked-in reviewed test, outside C1, with a minimal environment. It
  imports only a canonicalized JUnit subset.

## Rejected alternatives

- **One profile model with optional graph fields.** Rejected: it would
  change every M07 profile digest and weaken the graph profile grammar.
- **Computing the dependency gap from hidden occurrences.** Rejected: a
  readable signal that a hidden dependency exists is a noninterference
  violation.
- **A human-authored discrepancy in every fixture load.** Rejected:
  independent review would need a second human approver in each load. The
  review note is imported by a producer and attributed to it.
