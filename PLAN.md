# PLAN.md — C1 MVP roadmap

**Status:** planning scaffold; no milestone is implemented, tested, or approved by the existence of this file.  
**Baseline:** C1 project specification v0.2 and MVP architecture v0.2, plus the software-code/documentation use-case extension discussed afterward.  
**Execution policy:** each milestone is planned separately before implementation. This roadmap defines outcomes and tests, not every milestone's internal task breakdown.  
**Development instructions:** [AGENTS.md](AGENTS.md).

## 1. Product outcome and boundaries

Deliver one self-hostable C1 instance with one shared, versioned knowledge repository. Humans, applications, and external agents use the same authenticated APIs to contribute and retrieve authorized knowledge. Canonical identity is independent of producer, project, and access policy. No mandatory workspace or project database exists.

The MVP provides entities, aliases, keywords, assertions and typed relationships, evidence, provenance, temporal selection, reviewed ChangeSets, granular resource authorization, ordered document parts, deterministic document reconstruction, and consumer-ready context in Markdown and structured form.

The reference architecture uses an existing TerminusDB backend, OIDC with Keycloak as the reference provider, OpenFGA-backed authorization, and one modular C1 application with a basic Explorer. Backend capabilities, exact versions, editions, and licenses must be verified before reliance. Supporting identity/security persistence is not a second knowledge store.

The software use cases add a data-only software profile, source-snapshot applicability, coverage metadata, and task-specific context selection. External producers ingest code/documentation through APIs. C1 does not become a compiler, IDE, CI executor, or autonomous documentation writer.

### Fixed exclusions

No mandatory LLM or AI key, embeddings, semantic/vector search, automatic synonym generation, internal LLM extraction, research agent, plugin system, Graphiti/TypeDB/Cognee dependency, additional graph backend, unrestricted SPARQL endpoint, full OWL reasoner, cross-instance federation, multi-tenant SaaS administration, rich collaborative editor, or arbitrary binary-document renderer.

Separate installations serve administratively independent customers. Projects/collections/views are optional organization and filters; they are not ACL grants, storage partitions, or transaction boundaries.

### Planning conventions introduced by this file

Milestone IDs, evidence-report paths, fixture names, test IDs, and the status workflow below are implementation-planning conventions. They are not claims that these files, commands, fixtures, or services already exist. The active milestone plan chooses concrete tools, files, and executable test commands after inspecting the repository.

## 2. Plan one milestone independently

Only the owner-selected milestone receives a detailed implementation plan. Do not create speculative detailed plans for later milestones or interpret the roadmap as authorization to execute the entire project.

Workflow:

`NOT_PLANNED → PLANNED → APPROVED → IN_PROGRESS → VERIFYING → VERIFIED`

Use `BLOCKED` with a recorded reason when prerequisites or verification cannot be satisfied. A failed verification returns work to `IN_PROGRESS` or `BLOCKED`; it does not silently remove the failed test. Only an explicit owner decision may change required scope. User authorization may cover planning and implementation together, but an unapproved plan does not authorize implementation by itself.

The detailed plan is `docs/milestones/Mxx.md`. The completion report is `docs/milestones/Mxx-report.md`. Both are created for the active milestone, not prefilled with fictitious outcomes.

### Required contents of an individual milestone plan

| Section | Required content |
|---|---|
| Authority and starting state | Source baseline, relevant approved changes, actual code revision, prerequisite reports, and owner authorization. |
| Goal and boundaries | This milestone's observable result, exclusions, and affected invariants. |
| Decisions to resolve | Verified dependency capabilities, exact formats, interfaces, storage/security choices, and bounded alternatives. |
| Work breakdown | Small tasks, file/module ownership, necessary migrations, and safe integration order. |
| Test implementation | Map every roadmap test ID to executable tests, exact fixtures, expected results, and failure conditions. |
| Verification commands | Actual commands available in the repository, environment prerequisites, exit-code expectations, and regression selection. |
| Recovery and security | Failure points, rollback/recovery behavior, permission changes, and secret handling. |
| Handoff | Deliverable paths, demo procedure, evidence report, unresolved issues, and gate criteria. |

Detailed plans cannot weaken the fixed requirements. If a technical proof fails, propose a bounded revision for the owner instead of inventing capability or silently replacing the architecture.

### Completion evidence required for every milestone

The report identifies the implementation revision, exact commands, dependency/service versions, fixtures, output artifacts, and PASS/FAIL/NOT_RUN results for every test below. It records regressions, review findings, and limitations. Keep sensitive logs out of public evidence.

Every listed test is a **future verification contract**, not an already-existing executable test. No mandatory check may be skipped, marked expected-failure, or replaced with a mock-only demonstration to declare a milestone verified.

Use real pinned services for integration behavior. Unit tests can use mocks, but mocks cannot establish database atomicity, identity validation, authorization consistency, or backup recovery.

No-AI behavior and resource authorization are regression obligations for every feature, not work deferred until the final milestone. Before the protected API exists, foundation experiments stay isolated and are not exposed as an unsecured product.

## 3. Milestone map

The order below deliberately separates the three software-agent workflows. Each row is an independently planned delivery gate.

| ID | Milestone | Prerequisites | Verifiable result | Initial status |
|---|---|---|---|---|
| M00 | Baseline and development harness | None | Attributed local specification, accepted extension, and reproducible checking harness | PLANNED |
| M01 | Infrastructure and feasibility proofs | M00 | Pinned open-source stack with measured transaction/security/interchange proofs | PLANNED |
| M02 | Canonical model and standards profile | M01 | Validated, portable knowledge records and software-extension boundaries | NOT_PLANNED |
| M03 | Identity and current resource authorization | M02 | Fail-closed principals, scopes, bindings, and controlled security operations | NOT_PLANNED |
| M04 | Reviewed knowledge writes and history | M03 | Atomic, retry-safe ChangeSets and policy-safe historical reads | NOT_PLANNED |
| M05 | Shared identity and deterministic query API | M04 | Keyword/structured retrieval and a permission-correct multi-company directory | NOT_PLANNED |
| M06 | Scoped documents and reconstruction | M05 | Ordered text retrieval with mixed visibility and preserved evidence | NOT_PLANNED |
| M07 | Consumer-ready context and cross-project reuse | M06 | Deterministic context packages for the PaperTrader/Robotelier fixture | NOT_PLANNED |
| M08 | Software profile and source-version ingestion | M07 | Version-pinned code/documentation records and explicit import coverage | NOT_PLANNED |
| M09 | Coding-agent test-development context | M08 | Reproducible test-writing context separating contract from implementation | NOT_PLANNED |
| M10 | Documentation-first support context | M09 | Two-stage support retrieval with a stable software target and controlled fallback | NOT_PLANNED |
| M11 | Cross-software documentation-update context | M10 | Applicable, source-grounded context and reviewable documentation revisions | NOT_PLANNED |
| M12 | Human Explorer | M11 | Browser workflows using the same secured API and context packages | NOT_PLANNED |
| M13 | Release hardening and operational acceptance | M12 | Independently repeatable deployment, recovery, and complete acceptance evidence | NOT_PLANNED |

The baseline's four broad delivery phases are decomposed here rather than discarded: foundations in M00–M03; durable knowledge in M04–M06; context in M07 and M08–M11; Explorer/operations in M12–M13.

## 4. Shared fixtures and test rules

### Fixture families

| Fixture | Minimum contents and purpose |
|---|---|
| `core-knowledge` | Shared entities, typed literals, aliases, keywords, conflicting claims, evidence, manual claims, and uncertain time. |
| `directory` | Company A, Company B, one shared Person, shared contact details, Company A-only note, selected-user phone, at least three principals, and distinct permissions. |
| `scoped-document` | At least five ordered parts across three policies, two reader populations, an unrelated hidden part, and a historical revision. |
| `cross-project-batteries` | One canonical Tesla company, separate financial instrument, illustrative Optimus/vehicle/Megapack product and battery versions, two producers, a third consumer, duplicate source, conflict, incomplete measurement, irrelevant product, and hidden relation. All values are synthetic. |
| `software-integration` | Two tiny synthetic code repositories, at least two snapshots per relevant component, an explicit interface contract, a shared capability, documentation current for one target and outdated for another, TestCases/TestRuns, import errors, and restricted code. |

All fixtures use stable synthetic IDs and independently specified expected outputs. Tests must not require private company repositories, production identities, external LLMs, or a paid provider. A deterministic producer client is not an agent runtime or plugin.

### Test rules

Use exact result sets, order, record counts, state transitions, revision/target identities, and denied-content assertions where applicable. For safety tests, compare permitted observations before and after adding hidden records: hidden content must not alter public matches, totals, paths, snippets, or reconstructed material.

Golden context fixtures check facts, excerpts, qualifiers, citations, ordering, and declared incompleteness rather than an LLM's prose preference. Canonicalize only explicitly volatile fields when testing deterministic output. Do not erase meaningful differences to make snapshots pass.

Separate content revision from current security state in every historical test. For software, also pin source revisions and target configurations. An old C1 snapshot is not a grant to use old permissions, and a C1 revision is not a software release.

Once the secured API exists, routine fixture ingestion uses it. Direct backend access is allowed only inside isolated backend probes and explicit fault-injection setup; it must never become an application bypass.

---

## M00 — Baseline and development harness

**Goal:** establish a versioned, attributed starting point and a repeatable development workflow without pretending the product exists.

**Verifiable outputs**

- Repository-local copies of the v0.2 specification and architecture, source identity/revision notes, and a separate software-use-case addendum containing A18–A22.
- A short README distinguishing intended capabilities from implemented ones; AGENTS.md and this roadmap at repository root.
- A minimal development/test harness, formatting/static checks appropriate to the selected language, a CI entry point, and conventions for milestone plans/reports.
- A list of genuinely open implementation choices: versions, language/framework, service configuration, binding-publication protocol, and source-format coverage.

**Specific tests**

- **M00-T01 — Baseline fidelity:** compare local copies with the identified sources; A01–A17 and G1–G9 retain their meaning. Record A18–A22 as the conversation-derived extension, not as pre-existing v0.2 text.
- **M00-T02 — Clean start:** from a clean checkout, the documented bootstrap and first checking command succeed without any AI key. Only the harness is claimed to work.
- **M00-T03 — CI detects failure:** deliberately failing a temporary harness assertion makes the check and CI job fail; removing it restores the expected harness result.
- **M00-T04 — No fabricated state:** the roadmap has no completed implementation milestone, source snapshots are attributed, and documentation contains no invented installation/release claims.
- **M00-T05 — Secret hygiene:** a synthetic secret placed in a disposable test location is rejected by the selected repository check; committed baseline and fixtures contain no real credentials.

**Plan separately:** repository layout, language/runtime selection consistent with the reference proposal, command names, source-snapshot method, and evidence storage.

**Exit gate:** a new contributor can reproduce the harness and identify exactly what is approved, proposed, and unimplemented. M00 itself must have a separate plan before execution.

## M01 — Infrastructure and feasibility proofs

**Goal:** prove the risky infrastructure assumptions before building features around them.

**Verifiable outputs**

- A pinned, local reference stack for TerminusDB, identity, authorization, and required supporting persistence, isolated from production data.
- Actual dependency/edition/license inventory and ADRs recording verified operations, rejected assumptions, and any proposed change needing owner approval.
- Executable proof fixtures for transactional writes, revision reads, validation interoperability, authorization freshness, and interrupted publication.
- A chosen, evidence-backed boundary for knowledge revisions versus workflow metadata and durable receipts; no fake cross-service transaction guarantee.

**Specific tests**

- **M01-T01 — Open-source artifact check:** each mandatory artifact has recorded origin, pinned version/digest, actual license, and required notices; the demonstrated path uses no proprietary or enterprise-only feature.
- **M01-T02 — Atomic batch:** induce failure within a multi-record update; the selected write method exposes either all intended records plus its receipt or none, never a partial visible commit.
- **M01-T03 — Stale base and lost response:** two writes based on the same knowledge revision cannot lose an update. After committing and dropping the response, receipt reconciliation finds one committed outcome rather than applying twice.
- **M01-T04 — Independent revisions:** read two immutable knowledge revisions and show the expected differing values; security state is not read from those historical records.
- **M01-T05 — Fresh policy check:** revoke access and change a resource binding while retaining the user's old group membership; the tested authorization path denies the next protected probe.
- **M01-T06 — Interrupted publication:** kill the prototype between content and policy steps; after restart it blocks affected reads until reconciliation establishes a valid current state.
- **M01-T07 — Interchange probe:** round-trip one supported assertion with a language-tagged literal and provenance through an independent RDF/JSON-LD processor and the selected storage mapping without losing identity.

**Plan separately:** exact service versions, backend operations, lock/receipt strategy, journal location, consistency configuration, and fault-injection mechanics.

**Exit gate:** G1 and the foundational parts of G2/G3/G4/G8 have evidence. An unproven required capability blocks dependent work; it does not authorize silently adding another database.

## M02 — Canonical model and standards profile

**Goal:** make the knowledge contract explicit and testable independently of HTTP and a domain-specific application.

**Verifiable outputs**

- Versioned RDF/JSON-LD contexts, supported vocabulary/profile, SHACL shapes, and tested mapping to backend record schemas.
- Entity, Assertion/relation, Source, Evidence, Activity, resolution, Document/DocumentPart, schema, and ChangeSet representations, with current authorization kept outside historical content authority.
- Documented keyword normalization and exact ANY/ALL semantics; temporal boundaries and uncertainty conventions.
- Minimal extension points expressed as data, including the forthcoming software profile, not executable capability plugins.

**Specific tests**

- **M02-T01 — Lossless supported round-trip:** preserve canonical IRIs, typed/language-tagged literals, separate assertion identities, qualifiers, evidence links, and provenance after import/export normalization.
- **M02-T02 — Invalid versus conflicting:** reject malformed record structure but accept two structurally valid contradictory claims about the same subject; also accept a legitimate multi-valued relationship.
- **M02-T03 — Unsupported input:** unsupported JSON-LD/SHACL constructs produce explicit diagnostics without partial persistence. A remote context is not fetched merely because it appears in input.
- **M02-T04 — Identity independence:** changing a label, project reference, or historical policy annotation never changes the canonical ID; a like-named entity is not automatically merged.
- **M02-T05 — Keyword cases:** test normalization, whitespace, case, phrases, language tags, duplicate coalescing, ANY, ALL, and empty filters against predetermined expected values, without stemming or invented synonyms.
- **M02-T06 — Time cases:** distinguish precise half-open intervals, unknown boundaries, explicitly unbounded intervals, and year-only dates. Do not fabricate a timestamp or substitute ingestion time.
- **M02-T07 — Safe extension:** add a small domain type/profile and validate a fixture without changing core application code; incompatible changes require an explicit migration proposal.

**Plan separately:** supported shape subset, literal representation, blank-node handling, normalization details, schema versioning, and mapping implementation.

**Exit gate:** G3 is reproducible for the defined profile; no public unrestricted query engine or LLM dependency has been introduced.

## M03 — Identity and current resource authorization

**Goal:** establish real protection before exposing knowledge features.

**Verifiable outputs**

- Trusted-instance configuration, OIDC/API identity validation, human/service principal attribution, and the proposed OpenFGA authorization model.
- Current resource-to-policy bindings, reusable scope permissions, scoped creation/review rights, and separate schema/access/operational administration.
- Audited security operations for provisioning, membership, re-scoping, declassification, and recovery, using the protocol proven in M01.
- A protected test surface and fail-closed readiness behavior; still no unrestricted production CRUD endpoint.

**Specific tests**

- **M03-T01 — Token rejection:** reject missing, expired, wrong-issuer, wrong-audience, wrongly signed, and inappropriate ID tokens on the API path. A user-supplied delegation field cannot impersonate another principal.
- **M03-T02 — Permission separation:** Reader cannot create or apply; Contributor cannot review unless separately granted; Reviewer cannot grant access; operational ownership does not silently read protected content.
- **M03-T03 — Independent resources:** allow a principal to see two entities but deny their relation and one assertion/evidence record. Project membership creates no permission.
- **M03-T04 — Current-binding regression:** move a resource from shared to restricted while the reader remains in the old scope; authorization for current and historical IDs uses the new binding and denies access.
- **M03-T05 — Binding failures:** missing, duplicate/invalid, unresolved, deleted-without-tombstone, or inconsistent binding states fail closed; unsafe scope deletion is rejected.
- **M03-T06 — Re-scope authority and recovery:** unauthorized broadening fails; an authorized security transition is audited; interruption at each publication step leaves no readable inconsistent state after recovery.
- **M03-T07 — Trusted boundary:** no client parameter selects another repository or activates an imported grant; loss of the authorization service denies protected operations.

**Plan separately:** exact policy model, inheritance semantics, token/session configuration, current-binding lookup, operation journal, and concurrency coordination. Tests use real identity/authorization services with synthetic resources.

**Exit gate:** G4/G8 infrastructure behaviors are verified. New feature paths must use this boundary from their first exposed version.

## M04 — Reviewed knowledge writes and history

**Goal:** deliver the first secure end-to-end write/read slice through the canonical store.

**Verifiable outputs**

- ChangeSet create, validate, approve, reject, and apply operations with exact-payload review and scope-aware authorization.
- Durable entity/assertion/source/evidence operations, atomic schema/data changes where required, idempotency receipts, and historical content inspection.
- Compensating corrections/restores and current-policy-safe visibility of drafts and review output.
- Integration tests using the real backend and current authorization, not direct client database access.

**Specific tests**

- **M04-T01 — Reviewed application:** a contributor proposes a source-backed assertion; validation, authorized review, and apply produce exactly one committed assertion, provenance activity, and apply receipt. An attributed manual claim is also accepted without pretending it has an external source.
- **M04-T02 — Review invalidation:** changing the approved payload invalidates approval; applying it fails until revalidated/reapproved. An independent-review policy rejects self-approval.
- **M04-T03 — Cross-scope atomicity:** a ChangeSet targets two scopes. Deny permission for one operation and verify neither change commits; grant the required authority and verify both commit together.
- **M04-T04 — Retry and crash:** replay an identical request and recover the same outcome; reuse its key with a different digest and reject it. Inject a crash before/after commit and verify no duplicate knowledge operation.
- **M04-T05 — Revision correctness:** review metadata does not accidentally invalidate its own intended knowledge base. A competing committed knowledge change does make the proposal stale, and stale apply cannot overwrite it.
- **M04-T06 — Restore versus security:** restore an older value using a new ChangeSet while the resource's current restrictive binding stays effective. Old content, drafts, and review details remain unavailable to unauthorized readers.
- **M04-T07 — Schema and conflict integrity:** an invalid reference or failed migration writes nothing; a valid competing claim preserves both sources; linked schema/data operations become visible together.

**Plan separately:** concrete API lifecycle, base-version semantics, durable workflow metadata, receipt schema, migration boundary, and correction representation.

**Exit gate:** G2 and the write-related parts of G8 pass through the actual application API. All ordinary writers use ChangeSets; security changes remain separate.

## M05 — Shared identity and deterministic query API

**Goal:** deliver usable structured retrieval and prove the multi-company address-book case.

**Verifiable outputs**

- Instance-level catalog/entity/assertion/evidence/history APIs with filters, bounded authorized traversal, stable cursors, and explicit errors/limits.
- Manual resolution, reviewed merge/split/undo, aliases, and canonical identity reuse across optional project views.
- The directory fixture with one shared Person and differently protected contact assertions.
- Query-plan and expected-result tests proving permission constraints precede matching and aggregation.

**Specific tests**

- **M05-T01 — Shared directory:** Company A and Company B readers find the same Person ID, while the company-private note and selected-user phone appear only for the prescribed principals.
- **M05-T02 — Filter contract:** combine type, exact keywords, label/alias, property, relationship, and valid-time filters; assert exact visible IDs and order, including unknown-validity handling.
- **M05-T03 — Hidden-data noninterference:** add an unauthorized matching entity, keyword, assertion, and linking edge; public results, counts, match explanations, and permitted paths remain unchanged.
- **M05-T04 — Safe identity changes:** rename, merge, split/undo, and add project references while preserving canonical identity/history where specified and without widening the moved assertions' policies. Inaccessible duplicates are not disclosed.
- **M05-T05 — Cursor behavior:** ordinary inserts after page one do not change its captured content snapshot. Revocation or re-scoping before page two is enforced; invalid authorization-dependent state restarts safely rather than returning forbidden data.
- **M05-T06 — Limits and errors:** enforce page/traversal/node/time bounds, reject malformed filters and arbitrary backend-query attempts, and avoid confirming hidden-resource existence through errors.
- **M05-T07 — View neutrality:** a project filter narrows the authorized set; adding a hidden resource to a visible collection does not copy it, reveal it, or grant access.

**Plan separately:** supported filters and datatypes, cursor encoding, normalization use, traversal templates, merge mechanics, and limits within the baseline's proposed defaults.

**Exit gate:** A03/A04/A06/A09/A13 and the applicable parts of A17 pass. Security is based on current bindings, not historical scope fields.

## M06 — Scoped documents and reconstruction

**Goal:** deliver text storage whose retrieved view is assembled from authorized parts.

**Verifiable outputs**

- Document and DocumentPart writes through ChangeSets, deterministic ordering, exact textual content, and evidence associations to source versions.
- Authorized document listing, part inspection, compact reconstruction, history, and export through the common API.
- Text rendering with no browser-side hidden payload and a clear complete-source versus excerpt representation for code-like text.
- The scoped-document fixture and golden reconstructed views.

**Specific tests**

- **M06-T01 — Ordered views:** a document with at least five parts across three scopes yields the exact expected ordered content for two different readers.
- **M06-T02 — No hidden structure:** unauthorized content, part IDs, headings, positions, omitted-part counts, and default redaction placeholders do not appear in returned metadata or renderer input.
- **M06-T03 — Search/export parity:** a term found only in a hidden part does not cause a public match or change counts; export includes only authorized material.
- **M06-T04 — Historical re-scope:** restrict a part while its former readers keep their old group membership; current retrieval, older revisions, and export all use the new binding.
- **M06-T05 — Content integrity:** preserve selected code/text bytes and formatting according to the declared encoding contract; a partially retrieved code unit is an excerpt, never silently labeled complete or executable.
- **M06-T06 — Structure validation:** reject dangling document references, cycles if nesting is supported, invalid ordering, and unauthorized insertion/move operations without partial commits.
- **M06-T07 — Safe rendering:** markup and command-like source text cannot inject executable UI content, fetch remote resources, or execute commands during retrieval.

**Plan separately:** ordering keys, nesting subset, source-location representation, text formats, evidence selectors, and safe rendering details. Rich collaboration and binary-office parsing stay excluded.

**Exit gate:** A14 and G5 pass, including current bindings on historical parts and no hidden content in the client.

## M07 — Consumer-ready context and cross-project reuse

**Goal:** turn permitted structured knowledge into immediately usable context without an LLM.

**Verifiable outputs**

- `POST /v1/context` with explicit selectors, versioned data-only path profiles, formats, budgets, and continuation.
- A deterministic Context Builder producing Markdown and equivalent structured results from one authorized selection.
- Explicit topic/alias resolution where configured, separate from unchanged exact keyword matching.
- The cross-project-batteries fixture and golden context outputs with assertions, excerpts, citations, qualifiers, and limits.

**Specific tests**

- **M07-T01 — Cross-project reuse:** PaperTrader and Robotelier producer clients use one canonical Tesla company; the third consumer retrieves relevant battery context without choosing either project or using AI credentials.
- **M07-T02 — Graph relevance versus keywords:** find a battery lacking the Tesla keyword through an approved company/product/component path, while the exact keyword ALL query retains its original behavior. Exclude an unrelated nearby product.
- **M07-T03 — Authorized paths:** visible endpoints connected only by a hidden relation do not match. Hidden evidence, source titles, excerpts, and topic labels never enter the package or its explanatory metadata.
- **M07-T04 — Evidence integrity:** preserve a conflict and incomplete measurement; distinguish product/version, quantity, unit, and conditions. Two imports of one original source are not presented as independent corroboration.
- **M07-T05 — Usable payload parity:** facts and available excerpts are included, not only referenced. Markdown and structured outputs contain the same selected evidence and qualifications, with resolvable citation targets.
- **M07-T06 — Determinism and budget:** repeat a request with the same content revision, profile, and security state; selected content and order match. A smaller budget declares truncation and continuation without silently dropping essential caveats.
- **M07-T07 — Ambiguity and revocation:** unresolved selectors return authorized disambiguation or a non-guessing outcome; a revoked continuation cannot reuse earlier permissions. Missing requested fields describe only the returned data.

**Plan separately:** request grammar, profile subset, ranking/order rules, budget unit, citation encoding, deterministic templates, and continuation strategy. Do not add semantic search or a natural-language planner.

**Exit gate:** A15/G9 pass with the no-AI environment and consumer-ready golden fixtures.

## M08 — Software profile and source-version ingestion

**Goal:** represent code and documentation from multiple software products without conflating their versions or promising an all-language analyzer.

**Verifiable outputs**

- A data-only software profile for products, source repositories, releases/snapshots, capabilities, symbols, interface operations, test definitions, and test runs.
- A declared target-set representation for multiple source versions and relevant configurations, separate from the C1 revision.
- Ordinary API import contracts with producer/tool identity, immutable source locators/digests, coverage, errors, and unresolved relationships.
- Two tiny synthetic source repositories and versioned documentation/contract artifacts, plus a deterministic producer demonstration. External format mappings are documented for the subset actually selected.

**Specific tests**

- **M08-T01 — Independent identities:** two repositories containing the same unqualified function name produce distinct occurrences; one logical capability can link both. Adding a project view does not create another C1 repository or copy symbols.
- **M08-T02 — Target pinning:** select A at snapshot a1 and B at b1; all relevant code, contracts, and applicability records correspond to those targets. Availability of a2/b2 must not silently change the request.
- **M08-T03 — Immutable evidence:** resolve every returned source excerpt to its pinned snapshot, path, and permitted range/digest; a branch label moving later does not change that evidence.
- **M08-T04 — Partial ingestion:** report one failed file/producer operation. The run remains explicitly partial; missing relationships are not asserted absent, and older extraction is not relabeled as analysis of the new snapshot.
- **M08-T05 — Repeatable import:** importing the same producer/snapshot payload is idempotent; conflicting claims from another producer preserve separate attribution rather than silently replacing each other.
- **M08-T06 — Relationship semantics:** distinguish definition/reference, declared/static call, interface mapping, interpretation, and observed execution. A symbol name or static reference alone cannot become proof of a runtime call.
- **M08-T07 — Protected sources:** current source-resource bindings apply to historical snippets and derived records; unauthorized source paths/metadata do not leak through coverage reports or duplicate checks.

**Plan separately:** first fixture language(s), source formats, exact identity/occurrence mapping, target-set semantics, incremental-import completion rules, and supported external producer integration. Evaluate existing standards/indexers rather than building a compiler into C1.

**Exit gate:** the software model and A21 source-consistency behavior work through ordinary APIs with no LLM or mandatory new backend. A fixture import is not company-wide production ingestion.

## M09 — Coding-agent test-development context

**Goal:** supply the evidence a coding agent or human needs to write an appropriate test, without making C1 generate or execute it.

**Verifiable outputs**

- The `test-development` context profile and golden packages for a documented capability and its code symbols.
- Included expected behavior, relevant implementation, interfaces, available fixtures, test conventions, execution instructions from attributed sources, and unresolved differences.
- A deterministic consumer demonstration and a separately executed synthetic test validating the fixture's contract/context linkage; C1 remains a data service.
- Distinct records and presentation for TestCase definition, TestRun result, mocked dependency, and actual integration evidence.

**Specific tests**

- **M09-T01 — Required context:** a target-specific request returns the applicable contract/documentation excerpt, code signature and relevant body, necessary available types/fixtures, nearby tests, and cited execution instructions.
- **M09-T02 — Do not canonize a bug:** the fixture implementation violates an explicit documented condition. The package preserves the discrepancy; it does not rewrite the normative expectation to match the implementation.
- **M09-T03 — Definition versus execution:** a test file without a matching run is labeled as a definition, not a pass. A run from a different commit/configuration is not verification of the requested target.
- **M09-T04 — Mock versus integration:** a test using a simulated Software B is not reported as proof that the A–B integration passes; a separate matching integration run retains its exact target and result.
- **M09-T05 — Consumer reproducibility:** using the supplied fixture context, the reviewed external test targets the intended condition and produces the predetermined failure/pass on the defective/fixed fixture snapshots. This tests the fixture evidence, not arbitrary LLM coding quality.
- **M09-T06 — Restricted or incomplete code:** partial code is represented as an excerpt; unresolved dependencies are disclosed only as authorized incompleteness. No hidden source is fetched by the browser or consumer through citation expansion.

**Plan separately:** profile fields, bounded dependency paths, distinction between conformance and characterization goals, fixture expectations, and the external demonstration runner.

**Exit gate:** A18 passes. The consumer can begin test development from the material returned, without pretending the core is an agent or CI executor.

## M10 — Documentation-first support context

**Goal:** implement explicit two-stage retrieval: applicable documentation first, targeted implementation context second.

**Verifiable outputs**

- `support-documentation` and `support-implementation` profiles with documented deterministic precedence and target selection.
- A two-request demonstration carrying the same source target set and content snapshot, with current authorization reapplied to each request.
- Separate presentation of official/documented guidance, attributed implementation interpretation, and matching observed test evidence.
- Coverage/gap inputs that allow an external consumer to request missing aspects; no automated LLM judgment of answer sufficiency.

**Specific tests**

- **M10-T01 — Applicability before age:** an old but target-applicable guide outranks a newer guide for a different release. A guide explicitly obsolete for the target is not promoted simply because it is documentation.
- **M10-T02 — Focused fallback:** the first package lacks a declared retry/timeout aspect. A second explicit request returns only the pertinent implementation/configuration/test paths rather than dumping unrelated code.
- **M10-T03 — Same target:** between the two requests, ingest a newer software snapshot. The fallback still uses the original selected target, or explicitly requires the caller to choose a new one; it never mixes versions silently.
- **M10-T04 — Evidence labels:** code-derived information is not labeled as an official supported procedure. Known, authorized contradiction/applicability warnings accompany documentation-first results instead of being hidden by source priority.
- **M10-T05 — No privilege escalation:** a documentation-only support principal cannot gain code access by naming the implementation profile. An unavailable result does not reveal private code existence.
- **M10-T06 — No sufficiency oracle:** an unanswered free-text issue does not trigger an internal model, arbitrary query, or autonomous fallback. Explicitly requested absent fields are reported as missing in the returned material.

**Plan separately:** source-priority rules, gap selectors, target/snapshot continuation, attribution labels, and permitted response audience. Publication rights remain separate from source read rights.

**Exit gate:** A19 passes with documentation and code retrieved through separate authorized requests and no AI service.

## M11 — Cross-software documentation-update context

**Goal:** support an external author updating obsolete documentation for a capability implemented by two products.

**Verifiable outputs**

- A `documentation-update` profile combining existing document structure, target applicability, relevant A/B implementation, interface contract, and matching test evidence.
- Version-relative and part-relative documentation review/applicability records, with explicit evidence and provenance.
- A reviewed new documentation draft in C1 with derivation links, preserved previous versions, and a declared audience/publication state.
- Separation between C1 draft/review and any external source-repository publication receipt; no automatic Git write or claimed merge.

**Specific tests**

- **M11-T01 — Both sides of the feature:** an A–B target request includes each component's responsibility and the explicit connecting contract; similar names alone do not create an integration.
- **M11-T02 — Relative obsolescence:** the old document stays applicable to a1/b1 while one part is out of date for a2/b2. Updating that part does not globally mark every version or section obsolete.
- **M11-T03 — Review candidate, not proof:** a changed documented dependency creates a `needs review` outcome under the declared rule. It does not by itself assert that the prose is false. An attributed check can establish a specific discrepancy.
- **M11-T04 — Draft lineage:** the new draft records the target source snapshots, supporting evidence and author; its assertions do not erase unresolved differences or the old document history.
- **M11-T05 — Separate publication:** committing/reviewing the C1 draft does not set an external Git document to published. Only an explicit imported publication result can record that external state.
- **M11-T06 — Audience and freshness:** unauthorized broadening of a code-derived draft is rejected or remains non-public pending explicit review. A changed requested target before final approval requires revalidation of applicability; missing compatibility evidence remains unknown.
- **M11-T07 — Historical protection:** older code, draft parts, source citations, and review reports continue to obey current bindings after revocation/re-scoping.

**Plan separately:** applicability states and evidence, change-to-review-candidate rules, cross-product path profile, draft workflow, and externally reported publication mapping. Generation of new prose remains outside the deterministic core.

**Exit gate:** A20 and the publication portion of A22 pass, with independently inspectable evidence for both software products.

## M12 — Human Explorer

**Goal:** let a human perform the same core workflows without special database access, an LLM, or a command-line-only interface.

**Verifiable outputs**

- Basic instance-level browsing, manual entity/schema/profile forms where authorized, keyword/alias editing, relationships, assertions, evidence, conflicts, and history.
- Document viewing, context preview, optional project filters, ChangeSet preview/review, and authorized scope-management surfaces.
- API parity checks, safe rendering, keyboard-accessible list/detail workflows, and reproducible browser demonstrations.
- Version/applicability and uncertainty indicators for software contexts without a separate privileged software UI backend.

**Specific tests**

- **M12-T01 — Human/API parity:** a person creates and reviews a source-backed assertion through the browser; an ordinary API client performs the equivalent workflow and both produce the expected attributed records.
- **M12-T02 — No workspace detour:** navigate the shared directory and cross-project context without creating/selecting a workspace. Project filters do not change canonical IDs or access rights.
- **M12-T03 — Hidden-data absence:** inspect browser/network payloads for mixed-policy documents, code, relations, and contexts; forbidden content is never delivered and merely hidden with client code.
- **M12-T04 — Role enforcement:** a reader cannot apply by changing a request; an unauthorized reviewer cannot inspect/apply a full protected ChangeSet; schema and scope actions enforce their distinct permissions server-side.
- **M12-T05 — Safe presentation:** script-like labels, source excerpts, schema hints, and Markdown cannot execute code or load unauthorized content. Core workflows remain usable by keyboard.
- **M12-T06 — Evidence clarity:** the UI shows selected instance, revision, optional filters, source target, conflicts, excerpt/full status, and truncation consistently with the API rather than implying verified truth or complete source.
- **M12-T07 — Revocation:** after a grant or binding change, the next browser fetch is reauthorized; old history/context links cannot reopen restricted material.

**Plan separately:** frontend choice, screen layout, accessibility checks, approved widgets, browser-test framework, and API/client session integration.

**Exit gate:** A02 and the human-facing portions of A01/A14/A15/A18–A22 pass against the same secured APIs. A whole-graph visualization is not required.

## M13 — Release hardening and operational acceptance

**Goal:** produce a release candidate whose claims are backed by repeatable deployment, recovery, and acceptance evidence.

**Verifiable outputs**

- Pinned OCI images and a Compose-compatible reference deployment, including local identity/policy services, private networking, secrets, persistent volumes, health/readiness, and resource limits.
- Documented installation, API use, security administration, current-binding recovery, backup/restore, schema migration, import/export, and measured limitations.
- Final dependency/license inventory and required notices for the proposed open-source release; no dependency on an enterprise-only feature.
- Evidence for A01–A22 and G1–G9, including failure injection and the software extensions. A release candidate is not automatically published or deployed to production.

**Specific tests**

- **M13-T01 — Clean no-AI deployment:** from a clean test environment with required images already available, start the local stack with AI credentials absent and nonlocal provider egress blocked. Complete create/review/query/history/export, document assembly, all context profiles, and human/API flows.
- **M13-T02 — Full regression:** run A01–A22 and all required milestone checks against the candidate revision and pinned dependencies. No mandatory check is skipped or expected-failure.
- **M13-T03 — Knowledge-only restore:** back up knowledge, tighten permissions/bindings, then restore the old knowledge backup. Current grants and bindings remain authoritative, including historical-only resource tombstones.
- **M13-T04 — Full disaster recovery:** restore knowledge and security into an isolated deployment. It does not serve traffic until interrupted operations and security-state consistency are verified; older security backups are not silently treated as current grants.
- **M13-T05 — Failure/race matrix:** inject policy/backend outages, timeouts, lost responses, concurrent writers, binding changes, and restart points. Verify no partial visible knowledge commit, duplicate apply, stale authorization fallback, or unguarded publication.
- **M13-T06 — API and portability:** verify implemented OpenAPI routes, snapshot-export versus full-backup distinction, independent RDF round-trip, rejected unsupported constructs, and repeatable migrations.
- **M13-T07 — Measured bounds:** on a declared machine and synthetic dataset sizes chosen in this milestone's plan, measure latency, memory, write contention, context-size limits, and authorization costs. Publish measured limits and failure behavior, not untested scalability claims.
- **M13-T08 — Packaging/security audit:** no exposed backend credentials, real secrets, unauthorized public downloads, required AI SDK/model configuration, runtime plugin loader, or additional graph database. Required notices and actual licenses match pinned artifacts.

**Plan separately:** candidate versions, deployment commands, backup consistency procedures, declared benchmark datasets/thresholds, failure schedule, and release evidence locations.

**Exit gate:** every required acceptance scenario and infrastructure gate is verified or the candidate remains blocked. Publishing, deployment, and advancing beyond the MVP require their own authorization.

---

## 5. Acceptance register and milestone ownership

A01–A17 retain the v0.2 acceptance IDs and intent. A18–A22 carry the accepted software-use-case discussion into this roadmap. Entries below are summaries for navigation; the referenced source and milestone tests preserve their required detail.

| Acceptance ID | Required observable behavior | Primary milestone(s) |
|---|---|---|
| A01 | Full human/API operation without an AI key or mandatory workspace | M00, M12, M13 |
| A02 | UI and ordinary clients share validation/review with correct attribution | M04, M12 |
| A03 | Explicit keyword normalization, ANY/ALL, combined filters, stable pagination | M02, M05 |
| A04 | Stable identity, manual resolution, merge/split/undo, preserved history | M02, M05 |
| A05 | Conflicting claims retained; legitimate multiple values not misclassified | M02, M04, M07 |
| A06 | Valid-world time distinct from C1 knowledge revision; no fabricated dates | M02, M05 |
| A07 | Validated atomic writes, stale-base rejection, retry/crash reconciliation | M01, M04 |
| A08 | Reader/contributor/reviewer/schema/access permissions and independent review | M03, M04, M12 |
| A09 | No resource/edge disclosure through queries, cursors, views, or errors | M03, M05, M13 |
| A10 | Supported JSON-LD/RDF interoperability with explicit unsupported cases | M01, M02, M13 |
| A11 | Safe schema change and knowledge restore preserving current security | M02, M04, M13 |
| A12 | Documented recovery of knowledge/security; service failures fail closed | M01, M03, M13 |
| A13 | Multi-company address book reuses one Person with scoped assertions | M05 |
| A14 | Mixed-policy document reconstruction, search, history, export, and revocation | M06 |
| A15 | PaperTrader/Robotelier context reuse with relevant paths and usable evidence | M07 |
| A16 | Current bindings, not old snapshot scopes, control old and new content | M03, M04, M06, M13 |
| A17 | Multi-project/scope knowledge commits are atomic; views do not grant access | M04, M05 |
| A18 | Test-development context separates documented expectation, implementation, and runs | M09 |
| A19 | Documentation-first support with explicit targeted code fallback and stable target | M10 |
| A20 | Version-relative documentation update spanning two products and their contract | M11 |
| A21 | Partial/incompatible source acquisition never becomes a silently coherent target | M08, M09–M11 |
| A22 | Restricted code remains protected; excerpts/publication do not imply extra rights | M06, M08–M12 |

## 6. Existing architecture gates

| Gate | Preserved concern | Initial proof / final verification |
|---|---|---|
| G1 | Actual open-source edition/license and required backend capabilities | M01 / M13 |
| G2 | Atomic knowledge application, stale bases, receipts, schema/data coordination | M01, M04 / M13 |
| G3 | Supported interchange round-trip without semantic loss | M01, M02 / M13 |
| G4 | Current resource/edge authorization in a shared repository | M03, M05 / M13 |
| G5 | Scoped ordered document reconstruction without leakage | M06 / M13 |
| G6 | Shared multi-company identity without disclosure | M05 / M13 |
| G7 | No-AI operation across every mandatory path | Each exposed feature / M13 |
| G8 | Current bindings, re-scope recovery, and multi-scope write guarantees | M01, M03, M04, M06 / M13 |
| G9 | Consumer-ready, source-grounded, bounded cross-project context | M07 / M13 |

An early proof does not discharge later application tests. Software-context milestones extend G9's context discipline and G4/G8's security discipline; they do not replace the original fixtures.

## 7. Decisions deliberately deferred to separate plans

Exact dependency versions, HTTP/frontend framework, concrete OpenFGA model, durable security-operation journal, policy-generation/cursor strategy, query compilation mechanics, normalization version, document order keys, context budgeting, source-index format subset, first fixture languages, and packaging commands are chosen when the relevant milestone is planned.

Source priority and applicability must be defined for the consumer task, not as a universal “documentation always wins” or “code always wins” rule. Completeness is always relative to selected, authorized, successfully ingested sources. Unknown compatibility and missing data stay explicit.

The detailed planner must resolve any conflict between these choices and the source requirements before implementation. Do not solve uncertainty by introducing mandatory models, new graph databases, project partitions, or unreviewed policy shortcuts.

## 8. Source basis and status

**S1 — C1 project specification v0.2**, Todo, tab `t.ul3j4c28bh29`. Source of the baseline model, F01–F10, A01–A17, fixed scope, and current-binding requirements.  
[Open the project specification](PROJECT_SPECIFICATION.md)

**S2 — MVP architecture v0.2**, Todo, tab `t.s71tfshq1diu`. Source of the proposed service boundaries, reference stack, API paths, transaction/security separation, Context Builder, and G1–G9.  
[Open the MVP architecture](MVP_ARCHITECTURE.md)

**S3 — Subsequent software-code/documentation discussion in this conversation.** The owner requested company-wide source/documentation ingestion, coding-agent test context, documentation-first support with code fallback, and updating obsolete documentation across two products. The analysis preceding this request proposed the software profile, target-version sets, applicability/coverage, and A18–A22. The current request carries that extension into AGENTS.md/PLAN.md. It is not yet present in the retrieved v0.2 tabs; these files do not claim to update Todo.

**S4 — Current planning instruction.** Produce AGENTS.md and PLAN.md; divide work into milestones with verifiable outputs and specific tests, and plan each milestone separately. This is the authority for the execution policy and delivery structure in this file.

No product code, backend proof, security test, or milestone implementation was executed when drafting this roadmap. The next action is to select and separately plan **M00**, not to execute all milestones.
