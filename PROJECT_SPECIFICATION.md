# C1 — Project Specification

**Document edition:** Local source edition 1, consolidated on 2026-09-25.  
**Status:** implementation requirements for the planned MVP; not a software release.  
**Companion design:** [MVP_ARCHITECTURE.md](MVP_ARCHITECTURE.md).  
**Development instructions and roadmap:** [AGENTS.md](AGENTS.md), [PLAN.md](PLAN.md).

## 0. Authority, local use, and reading contract

This is a self-contained project source document. It consolidates the C1 project specification v0.2, the accepted decisions behind the corresponding architecture, and the subsequent software-code/documentation use cases. No Google Docs access, connector, private conversation, or external source document is required to understand the product requirements below.

The software extension is included explicitly in sections 10–11 and acceptance scenarios A18–A22. It is not represented as text that already existed in the original v0.2 specification. A01–A17 and F01–F10 preserve the baseline requirements. This local edition is a consolidation, not a claim that the cloud documents were updated or that implementation has started.

Within the project, subject to the execution environment's own instructions, apply this precedence:

1. The owner's current explicit instructions and accepted scope changes.
2. This specification, including the software extension and acceptance scenarios.
3. `MVP_ARCHITECTURE.md`, distinguishing fixed boundaries from proposed mechanisms.
4. `AGENTS.md` and `PLAN.md`.
5. The approved plan for the active milestone and its implementation decisions.

An architecture decision cannot silently remove a requirement. A conflict must be recorded and resolved explicitly. Statements marked **MUST** or **MUST NOT** are acceptance requirements. A **proposed** mechanism, example payload, field spelling, numeric limit, or implementation choice remains subject to its milestone plan unless stated otherwise.

**Local-source override:** earlier instructions to fetch the original Google Docs or retrieve an unseen software addendum are superseded by these two local source files. M00 must validate and version this local baseline, record its attribution, and establish the development harness. It must not require cloud-document credentials. Public standard and dependency documentation can still be consulted when implementing or pinning libraries; it contains no private C1 requirements.

Place the four Markdown files together at repository root. Detailed plans are created only for the selected milestone at `docs/milestones/Mxx.md`; verification reports are created at `docs/milestones/Mxx-report.md`. Creating this specification does not complete M00 or authorize implementation of every milestone.

### Contents

- [1. Product purpose and success condition](#1-product-purpose-and-success-condition)
- [2. Fixed MVP scope](#2-fixed-mvp-scope)
- [3. Boundaries, identities, and permissions](#3-boundaries-identities-and-permissions)
- [4. Logical knowledge model](#4-logical-knowledge-model)
- [5. Core functional requirements F01–F04](#5-core-functional-requirements-f01-f04)
- [6. Retrieval and consumer-ready context F05](#6-retrieval-and-consumer-ready-context-f05)
- [7. Controlled changes F06](#7-controlled-changes-f06)
- [8. Standards and security F07–F08](#8-standards-and-security-f07-f08)
- [9. Explorer and operations F09–F10](#9-explorer-and-operations-f09-f10)
- [10. Software profile and source applicability](#10-software-profile-and-source-applicability)
- [11. Software-agent workflows](#11-software-agent-workflows)
- [12. Acceptance scenarios A01–A22](#12-acceptance-scenarios-a01-a22)
- [13. Delivery and verification discipline](#13-delivery-and-verification-discipline)
- [14. Source basis and public technical references](#14-source-basis-and-public-technical-references)

<a id="1-product-purpose-and-success-condition"></a>

## 1. Product purpose and success condition

C1 is an open-source, self-hostable, versioned knowledge framework for humans, conventional applications, and external software agents. It provides a shared representation of entities, independently attributable assertions, relationships, documents, evidence, provenance, and time, through authenticated APIs.

C1 solves repeated fragmentation of identities and knowledge across applications. A company researched by one application and discussed in another should be one canonical entity, with separately sourced and separately authorized contributions. A consumer should be able to retrieve relevant knowledge without first knowing which producer collected it.

C1 separates:

- the identity of an object from its names and project associations;
- a source's claim from a selected application view of that claim;
- original evidence from the agent or script that imported it;
- world-valid time from C1 recording time and source revisions;
- content revisions from current security state;
- knowledge storage and presentation from AI reasoning.

C1 is not a new database, an LLM, a RAG pipeline, an autonomous researcher, a compiler, an IDE, or a CI executor. It builds above existing open-source infrastructure. Graphiti and similar agent-memory systems are not mandatory dependencies. Source-backed assertions and versioned graphs have precedents; C1 packages their semantics, authorization, APIs, and review workflow rather than claiming to invent them.

### Required end-to-end outcome

A human using the Explorer and an ordinary deterministic API client MUST each be able to create and review knowledge, query it, inspect evidence and history, reconstruct authorized documents, and obtain usable context with:

- all AI-provider credentials absent;
- no model download, embedding generation, or model execution;
- AI-provider network access blocked;
- no mandatory workspace or project selection;
- current resource-level authorization enforced.

External agents may use their own models, but remain ordinary authenticated clients. C1 does not need their provider key. **No AI key does not mean no authentication:** local service secrets, user login, and API access credentials remain necessary.

The working codename is **C1**. This document makes no public trademark-clearance claim for “C1” or “Component One.” Apache-2.0 is proposed for the project's original code, subject to release preparation and dependency review.

<a id="2-fixed-mvp-scope"></a>

## 2. Fixed MVP scope

### Included

| Area | Required result |
|---|---|
| Shared knowledge | One repository per instance; canonical entities reused across producers and optional project views. |
| Structured model | Types, properties, typed relationship assertions, source/evidence records, provenance, temporal qualifiers, and manual entity resolution. |
| Retrieval | Explicit keywords, names, aliases, typed filters, bounded graph traversal, deterministic ordering, history, and snapshot selection. |
| Context | Authorized Markdown and equivalent structured packages containing useful facts and available excerpts, not only identifiers. |
| Changes | Validation, review, atomic knowledge ChangeSets, idempotent application, corrections, and recoverable history. |
| Security | OIDC-compatible identities, reusable AccessScopes, per-resource/per-operation authorization, current bindings on old content, and explicit security administration. |
| Documents | Text Documents and ordered DocumentParts, exact text under a declared encoding contract, and authorized reconstruction. |
| Standards | A published, versioned RDF/JSON-LD profile, structural validation, provenance vocabulary, and explicit supported subsets. |
| Software use cases | A data-only software profile, immutable source snapshots, target-version sets, coverage/applicability records, and task-specific context profiles. |
| Human use | Basic Explorer, manual forms, evidence inspection, context preview, and controlled changes through the same API. |
| Operations | Reproducible self-hosting, pinned dependencies, health/readiness, secret handling, backup/restore, and verification evidence. |

Optional projects, collections, or saved views organize shared resources. They are not separate databases, namespaces, authorization grants, or transaction boundaries. A full project-management product is not required.

### Excluded

The MVP MUST NOT require plugins, Graphiti, TypeDB, Cognee, another graph backend, vector indexes, semantic similarity search, embeddings, LLM execution, internal LLM extraction, automatic synonym generation, automatic keyword generation, autonomous research, web crawling, or agent orchestration.

Also excluded: multi-tenant SaaS administration, cross-instance federation, arbitrary user ACL lists embedded in every record, unrestricted SPARQL, full OWL reasoning, binary office-document rendering, rich collaborative editing, simulation, prediction, and optimization.

For software sources, exclude a built-in compiler, universal language indexer, build/CI executor, autonomous documentation author, and automatic Git publication. External producers may perform those activities and submit their results through normal C1 APIs.

C1 can store textual source material as DocumentParts. It is not a universal document-management or source-control replacement. Binary attachments can remain externally referenced. Accepting externally derived assertions does not mean C1 runs the derivation.

<a id="3-boundaries-identities-and-permissions"></a>

## 3. Boundaries, identities, and permissions

### 3.1 Instance, repository, project, and scope

| Concept | Responsibility | Must not imply |
|---|---|---|
| Instance | Deployment endpoint, trusted configuration, operational administration. | Isolation from its own trusted infrastructure operators. |
| Repository | The single canonical knowledge store and revision/transaction boundary in the MVP instance. | Per-project or per-company partitioning. |
| Project/collection/view | Optional references and saved filters over existing resources. | New identities, automatic grants, or exclusive resource ownership. |
| AccessScope | Reusable authorization policy reference for resources and operations. | A container, graph, database, or namespace. |
| Principal | Authenticated human or service identity. | Authority inferred from a display name, source content, or arbitrary request field. |

There is no required `Workspace` resource or `workspace_id`. Administratively independent customers use separate deployments with separate routes, credentials, knowledge/security stores, and backup administration. Federation between those instances is not an MVP feature.

### 3.2 Principals and composable permissions

A principal is identified by trusted issuer plus subject, not mutable email or display name. Human and service principals are distinct and auditable. Delegation is recorded only when validated by the actual authentication/authorization flow. A client-supplied `on_behalf_of` value is not authority.

| Capability | Permitted purpose; always subject to resource checks |
|---|---|
| Read | Query and inspect permitted resources, history, evidence, documents, and exports. |
| Contribute | Propose or revise permitted knowledge changes. |
| Create | Create resources under an explicitly authorized target scope. |
| Review/apply | Review and apply operations for every permitted target in a ChangeSet. |
| Schema administration | Approve profile changes and migrations. |
| Access administration | Manage permitted scope memberships, current bindings, and declassification. |
| Operational ownership | Manage deployment/configuration; no silent content-read bypass. |

These are composable permissions, not a requirement to implement exactly one global role hierarchy. A reviewer does not automatically administer access; an operational owner does not automatically read every protected record. Broad content or administration grants must be explicit and audited.

### 3.3 Independent authorization

Entity, Assertion, every relationship assertion, Source, Evidence, Document, and DocumentPart MUST be independently authorizable. Software snapshots, code resources, TestCases, TestRuns, coverage/applicability records, and protected profile resources follow the same rules.

Reading an entity does not grant all of its assertions. Reading two endpoints does not grant their connecting relation. Adding a resource to a project does not grant project members access. Domain relationships such as `worksFor`, `owns`, and `memberOf` never become security grants implicitly.

A parent/default binding may be explicitly configured in current security state. Its semantics must be documented and consistent; inheritance is not inferred from arbitrary graph edges. Protected information cannot be duplicated into a less-protected entity description, keyword, cached summary, or citation to bypass a more restrictive assertion/evidence policy.

Complete multi-resource drafts, validation reports, and review payloads can be inspected only when the caller is authorized for all protected payload included. Review/apply additionally requires the relevant operation permission on every target. Independent review is enforced when enabled; a single-owner installation can explicitly allow self-approval.

<a id="4-logical-knowledge-model"></a>

## 4. Logical knowledge model

This is a logical contract, not a final database schema or JSON field specification. Public and storage representations must have tested mappings. Field names are illustrative unless fixed by the active milestone's API/schema contract.

### 4.1 Entity and schema profile

An **Entity** has an immutable identifier and canonical IRI in the configured instance namespace, approved type information, a label, optional description, aliases, explicit keywords, and lifecycle state. Identity is independent of producer, project, AccessScope, and backend layout. Current authorization is resolved separately.

A **SchemaProfile** is versioned data defining classes, predicates, value datatypes, ranges, constraints, and limited presentation/query hints. It contains no arbitrary executable code. New domain concepts can be added as profile data without modifying the core when they fit the supported subset. Contested domain properties belong in assertions, not only mutable display fields.

### 4.2 Assertion and relation

An **Assertion** is an individually addressable subject–predicate–object claim. The object is a resource identifier or a typed/language-tagged literal. A relationship claim uses another entity as object and receives its own policy binding. Quantified or qualified n-ary relationships can use a named relation/event resource with declared roles rather than forcing all information into an unqualified edge.

Separate assertions can express the same proposition from different sources. They retain identity and provenance even when the presentation groups duplicates.

Keep these dimensions separate:

| Dimension | Meaning |
|---|---|
| Origin | Manual, imported, or externally derived. |
| Review state | Reported, confirmed under a review policy, or disputed. |
| Lifecycle | Active, superseded, or retracted. |
| Confidence, when present | An attributed value with method/author; not automatically a calibrated probability. |

“Confirmed” is not a guarantee of truth. Storing a reified proposition does not automatically assert it as the selected-current truth of the graph. Any selected-current view is a derived presentation with a disclosed selection policy.

### 4.3 Sources, evidence, and provenance

A **Source** identifies material used to support a claim: title, source kind, locator, optional immutable revision or content digest, publication metadata, and authorized access information. A locator by itself is not verification and does not instruct C1 to fetch arbitrary content.

**Evidence** ties an assertion to a precise source version and location: document part, page, quote, API record, source-code range, or another supported selector. Include the useful excerpt when stored and authorized. Source metadata, evidence, and excerpts can have different current policy bindings.

A **ProvenanceActivity** identifies the authenticated actor, producing application/tool and version where supplied, method, inputs, affected resources, and outcome/revision. Original source identity is distinct from import activity. Two agents importing one source do not create two independent confirmations.

An assertion without an external source is allowed only as an explicitly attributed manual statement. It must not masquerade as independently sourced evidence.

### 4.4 Documents and parts

A **Document** is a stable, versioned textual/structured-text resource with metadata and an ordered structure of parts. It can itself be modeled knowledge; it need not only be an external source.

A **DocumentPart** has a stable identity, parent document reference, deterministic ordering information, text or supported structured textual content, optional heading/type, and an independently resolved security binding. Nested parts are optional; if supported, cycles and ambiguous ordering must be rejected.

A document's current security defaults can apply to its parts unless an explicit authorized binding differs. The content snapshot's historical scope annotation is not the effective policy.

The default reconstructed document is a **compact authorized projection**: omit unreadable content without exposing hidden part IDs, headings, positions, counts, or placeholders. The unrestricted structure manifest must not be delivered to an ordinary client. Metadata-only/redacted views are not required in the MVP and cannot be introduced without independent authorization for the exposed metadata.

Source code must not be reconstructed by silently concatenating fragments as if the result were a complete executable function. Distinguish a complete source unit from an excerpt; preserve permitted original text and formatting. Completeness can be asserted only when both source coverage and authorization justify it. Excerpt presentation must not reveal whether other material is hidden or merely outside the selection.

### 4.5 Time, resolution, and changes

An **Event** is a typed entity with explicit temporal qualifiers where known. Preserve publication time, observation time, world-valid time, system-recorded time, and source-software versions as distinct concepts.

An **EntityResolutionRecord** captures candidates and reviewed alias/mention decisions, including actor and rationale. Ambiguity is an acceptable stored state.

A **ChangeSet** contains its base knowledge revision, schema version, exact proposed operations, evidence, target resource identities, intended authorized creation scopes, validation results, review outcome, and application receipt. A security mutation is not an ordinary knowledge field edit, even if its provenance is recorded in knowledge history.

<a id="5-core-functional-requirements-f01-f04"></a>

## 5. Core functional requirements F01–F04

### F01 — Canonical identity and manual resolution

C1 MUST support lookup by ID, label, and explicit aliases over authorized resources without requiring a project selector. A producer should reuse an existing visible identity before proposing another one. Duplicate checks must not reveal inaccessible identities.

Exact identifiers may resolve deterministically. Similar names or shared keywords MUST NOT trigger automatic merging. A reviewed merge records the surviving identity and redirects, preserves old content history, and retains current policies for every affected assertion or resource. Redirect resolution is itself authorized.

Split, undo, or merge reversal requires an explicit reassignment plan for aliases and assertions. C1 does not guess ownership. Cross-instance merges are excluded. Renaming, changing a policy, and referencing another project do not change canonical identity.

### F02 — Explicit keywords and lexical retrieval

Keywords are editable through API and UI. Preserve original text and optional language tag plus a locally generated normalized value. The normalized form uses a documented, versioned combination of Unicode normalization, trimming, whitespace normalization, and case folding. Select exact details in the milestone plan.

Coalesce duplicate normalized keyword values for the same entity and language. Multiword keywords remain phrases. `ANY` matches at least one supplied exact normalized keyword; `ALL` matches all of them. An empty keyword filter adds no keyword condition.

Label/alias literal or prefix matching is separate from keyword membership. Do not silently stem, translate, infer synonyms, or rerank with a model. State the normalization version and authorized field match reason.

A declared topic scheme may explicitly map alternative labels to one concept for graph-context retrieval. That separate mode MUST NOT change exact keyword semantics or propagate a parent company's name into every descendant as a substitute for relationships.

Authorization constrains the matching set before ranking, counts, traversal, suggestions, and explanations. Hidden keywords or hidden document parts cannot make visible results match.

### F03 — Assertions, evidence, and conflicts

Creating an assertion requires evidence or an attributed manual statement declaring the absence of an external source. Preserve incompatible source claims and all authorized supporting evidence.

Automated conflict flags may use declared predicate rules, datatype comparisons, and overlapping valid intervals. Different targets alone are not proof of contradiction: two employment relationships may both be legitimate. Structural validity is separate from disagreement about the world.

The default view retains competing active authorized assertions. A selected-current view discloses its deterministic selection policy and supporting assertion IDs. An application display value must not erase alternatives.

Retraction records a new change and reason. Corrections and externally derived claims retain lineage. Confidential conflicting claims cannot change a public conflict flag or otherwise leak through the visible view.

### F04 — Temporal semantics

Queries distinguish `valid_at`, referring to modeled-world time, from `known_at` or an explicit knowledge revision. Select the content snapshot and apply world-time conditions to that snapshot, while authorization always uses current security state.

Precise intervals are half-open: start included, end excluded. An unknown boundary is not the same as an explicitly unbounded interval. Preserve precision and timezone information; a year-only date must not acquire a fabricated exact timestamp.

For strict `valid_at` queries, indeterminate validity is not a definite match. An explicitly requested `include_unknown` option may return those records separately with their matching rule. Never substitute ingestion time for missing validity.

Software-source revisions are an additional dimension, not a reinterpretation of `known_at`; see section 10.

<a id="6-retrieval-and-consumer-ready-context-f05"></a>

## 6. Retrieval and consumer-ready context F05

### 6.1 API/query contract

Expose instance-level operations for catalog, entities, assertions, sources, evidence, documents, context, resolution, ChangeSets, history, security administration, and export. Proposed paths include `/v1/entities`, `/v1/documents/{id}`, and `/v1/context`; the complete proposed surface is in the architecture.

The server chooses its repository from trusted configuration. Clients cannot supply arbitrary database paths, raw backend queries, or an effective principal. Optional project filters only narrow the already-authorized graph.

Support filters for IDs, types, label/alias, keywords, supported typed properties, relation predicates and targets, review/lifecycle state, and valid time. Neighborhood traversal is bounded by direction, allowed relationship types, depth, visited resources, and time.

Responses carry instance/repository identity, opaque knowledge revision, schema/profile version where applicable, deterministic ordering, and explicit truncation. A project identifier is optional organization metadata, never an access token.

Proposed starting limits are 50 results by default, at most 200 per page, neighborhood depth 1 by default and at most 3, plus a hard node budget and timeout. These are design defaults, not measured capacity claims. The milestone plan must select and test actual limits; profiles cannot evade global bounds.

Use stable revision-bound pagination. Every continuation rechecks current permissions and current bindings. A cursor cannot authorize content. A policy change that invalidates traversal state must produce a safe restart or an equivalently verified continuation, never reuse stale access.

Errors distinguish authentication, authorization, validation, stale-base, limits, and service failures without confirming hidden-resource existence. Reject unknown filters, unsupported datatypes, malformed IDs, and invalid temporal ranges explicitly.

### 6.2 Context-selection semantics

Context retrieval is a read operation, not inference. A request identifies an anchor entity or explicit selectors, a topic/aspect, a versioned data-only path profile, optional target/project/metric filters, output format, and size budget.

The profile resolves only declared IDs, aliases, or controlled-topic labels and follows bounded allowed typed paths. Ambiguous selectors remain ambiguous. The response explains the resolved query and supporting paths using only permitted metadata.

For an illustrative `batteries AND tesla` context request, Tesla is the company anchor and batteries is a declared topic. The profile may follow company → product → battery and then retrieve related claims/evidence. At least one battery can match without carrying the Tesla keyword. Unrelated nearby nodes must not match merely because they are a few graph hops away. Company, financial instrument, product, component, and version remain distinct identities.

### 6.3 Context package

The Context Builder MUST return material that a human or agent can use directly. Markdown and structured forms are generated from the same authorized selection.

| Package element | Required semantics |
|---|---|
| Interpretation | Resolved selectors, ambiguity, profile, target, and revision. |
| Orientation | Readable labels, relevant identities, versions/configurations, and authorized relationship explanations. |
| Facts | Self-contained assertions with values, datatypes/units, time, conditions, and review state. |
| Text | Relevant available excerpts, not merely evidence IDs or links. |
| Sources | Resolvable citations to authorized source versions and locations. |
| Provenance | Original source distinguished from importing agent and derivation. |
| Disagreement | Competing authorized claims and declared conflict basis. |
| Gaps | Requested fields missing in returned material, not a claim that the information does not exist anywhere. |
| Bounds | Truncation, budget, and authorized revision-bound continuation. |

Group results by relevant entity/product/version or task section. Do not mix quantities or incompatible software versions into a single apparent fact. Repeated source ingestion is not independent corroboration. A stored externally authored explanation may be included with attribution; the deterministic builder must not invent new conclusions or summaries.

Budgeting must preserve essential caveats and contradictory evidence for the claims presented. If a coherent unit cannot fit, explicitly defer it or return a bounded insufficiency outcome instead of silently removing qualifications. Exact budgeting units and templates are decided in M07.

Every selected endpoint, relation, assertion, document part, source title, and excerpt is independently authorized. A hidden relation cannot make a visible node relevant. Context output and completeness indicators cannot disclose hidden information.

### 6.4 Document retrieval versus topical retrieval

A document request reconstructs permitted parts of one selected document revision in order. A context request selects topical parts and their necessary permitted surroundings; it need not reconstruct entire source documents. Both use the same authorization and evidence semantics.

An empty result does not disclose whether other inaccessible parts exist. Historical reconstruction uses old content/order and current resource-policy bindings. Read rights do not imply permission to publish a reconstructed or derived document to another audience.

<a id="7-controlled-changes-f06"></a>

## 7. Controlled changes F06

All ordinary knowledge writes MUST pass through ChangeSets, including UI edits, imports, external-agent submissions, schema changes, document edits, and identity-resolution operations. Convenience endpoints cannot bypass validation/review.

The required lifecycle is:

```text
draft → submitted → validated → approved → applied
```

Rejected, stale, and failed outcomes are explicit. Editing operations after validation invalidates validation and approval. Application rechecks the exact approved payload, schema compatibility, base knowledge revision, current bindings, and every target operation permission.

A knowledge ChangeSet may span scopes and projects. Its knowledge operations and durable apply receipt become visible together or not at all. AccessScopes are not transaction boundaries. The initial architecture serializes repository writes; a stale base cannot overwrite a later committed change.

Bind idempotency to principal, instance/repository, and request digest. Repeating the same operation recovers its existing outcome. Reusing its key with different content fails. A lost response after a commit must be reconciled from a durable receipt, not blindly reapplied. An uncertain final outcome may return a recoverable operation identifier rather than false success.

Workflow bookkeeping must not make a proposal stale against itself. Concrete separation of content revisions, draft/review metadata, backend commits, and receipts is a required architecture proof, not an assumption.

Restores are reviewed compensating knowledge changes against current head. They do not erase audit records or restore old grants, bindings, or inherited defaults. Dependent schema and data changes become visible together, or the migration is rejected before publication.

Changing scope membership or a resource's effective policy binding is a separate authorized security operation. Ordinary content writes may record its provenance but cannot activate grants. New-resource publication needs coordinated content and security provisioning; no distributed transaction between security and knowledge stores is assumed.

<a id="8-standards-and-security-f07-f08"></a>

## 8. Standards and security F07–F08

### F07 — Supported standards profile

Use a versioned RDF 1.1 / JSON-LD 1.1 interchange profile, RDFS types/properties, SHACL structural validation, PROV-O provenance, and existing topic/time vocabulary such as Dublin Core, SKOS, and OWL-Time where appropriate.

Use named resources and typed/language-tagged literals. State exactly which blank-node, JSON-LD, and SHACL constructs are supported. Normalize supported constructs deterministically or reject them with diagnostics; never silently discard semantic content. Disable arbitrary remote contexts; bundle and pin approved ones.

Represent assertions as separately named statement resources with qualifiers and provenance. Recording a proposition does not automatically assert it in a current-world projection. Validate assertion records even when competing propositions disagree with a single-valued presentation constraint.

Schema changes are explicit and versioned. Support documented additive changes and reviewed migrations for incompatible changes. Profiles contain data, not arbitrary generated scripts. Every custom vocabulary term requires a defined meaning and a reason for not reusing an existing term.

Export must be readable by independent RDF tooling for the declared profile. Standards-first does not promise native backend support for every standard, full OWL inference, or unrestricted SPARQL. Do not silently turn the interchange format into a merely lossy export facade.

### F08 — Current resource authorization and revocation

All protected reads/writes check the actual principal, requested operation, and current binding of each relevant stable resource. Authorization constrains selection before public matching, aggregation, ranking, traversal, histories, identity checks, document assembly, and contexts; it is not cosmetic filtering after unrestricted results have already influenced the response.

In particular, enforce:

1. **Independent resources:** entities, relations, claims, source metadata, and fragments have distinct checks.
2. **Current bindings:** an old content record's `access_scope_id` is not authoritative.
3. **Current grants:** subsequent requests after revocation cannot reuse old memberships or positive cache decisions.
4. **Historical resources:** retain current bindings or deny tombstones for deleted resources still present in history; missing bindings fail closed.
5. **Noninterference:** hidden content must not change permitted result sets, counts, path existence, snippets, conflict flags, headings, explanations, or context selection.
6. **Security mutations:** broader or incomparable target audiences require explicit access-administration/declassification review; do not assume scopes form a total sensitivity ordering.
7. **Scope lifecycle:** reject scope deletion while protected current or retained historical resources still depend on it unless an explicit safe migration succeeds.
8. **Trusted routes:** requests cannot select another deployment, backend database, or identity. No client receives backend credentials.
9. **Failure behavior:** absent/untrusted identity validation, authorization, or current-binding state denies protected operations.
10. **Publication:** permission to read sources does not automatically authorize publishing their text or derived documentation to another audience.

An explicit inherited policy is resolved using current security state, never the old content hierarchy alone. A resource moved from shared to restricted remains restricted when an old content snapshot is requested, even if the user still belongs to the former shared scope.

A knowledge rollback cannot reopen old access. A cached context, cursor, evidence link, draft, or export endpoint cannot bypass reauthorization. Already delivered/downloaded bytes cannot be recalled; this design does not claim otherwise.

Broader threat-model and implementation questions, including timing/resource side channels, authentication revocation mechanics, and distributed consistency, must be recorded in the relevant security plan. Passing functional denial tests is not a claim of formally proven noninterference or physical isolation from infrastructure administrators.

<a id="9-explorer-and-operations-f09-f10"></a>

## 9. Explorer and operations F09–F10

### F09 — Minimum Explorer

The browser client MUST provide instance identification, authorized entity lists and manual forms, keyword/alias editing, supported filters, entity details, relationships, assertions, evidence, conflict display, time/history, document reconstruction, context preview, and ChangeSet preview/validation/review.

Expose schema and access-management operations only to authorized users. Optional project filters organize the same graph without mandatory workspace selection. Show selected content/source revisions, uncertainty, active filters, and truncation. Storing evidence does not mean it has been checked.

Core operations must be usable through keyboard-accessible list/detail interfaces. A bounded graph view may supplement them; whole-graph visualization, dashboards, and rich collaboration are not prerequisites.

Use approved presentation widgets. Schema hints, document Markdown, code comments, and labels cannot inject executable HTML/JavaScript, fetch arbitrary resources, or issue commands. Hidden text must never reach the browser and merely be hidden by CSS.

### F10 — Portability, operation, and licensing

Provide a reproducible self-hosted deployment with pinned dependencies/images, declared persistent volumes, secret injection/rotation, private backend networking, TLS, health/readiness, structured audit logging, and tested backup/restore instructions. No paid or proprietary service or AI key may be required.

Document snapshot export separately from full version-history backup. Authorized exports contain only permitted knowledge, schema/profile content where authorized, assertions, provenance, and revision metadata. Imports reject incompatible unsupported profiles and never activate security grants from imported fields.

Back up knowledge and security separately. A knowledge-only restore preserves current memberships, grants, and bindings. A full disaster recovery verifies security freshness and incomplete operations before serving traffic; restoring an old security backup is not silently treated as restoring current permissions.

Apache-2.0 is the proposed framework license. M01 must inspect the exact mandatory artifacts, editions, licenses, notices, and required capabilities. Do not rely on an enterprise-only operation or infer legal suitability from a product name. Final versions, library choices, and release notices require evidence.

Performance and limits must be measured on a declared machine and dataset. No unmeasured throughput, company-wide coverage, or scalability claim belongs in the README. Independent customers requiring administrative isolation use separate installations in this MVP.

<a id="10-software-profile-and-source-applicability"></a>

## 10. Software profile and source applicability

This section incorporates the accepted software-use-case extension. It does not require C1 to become a source-analysis engine. Software concepts are a data-only domain profile over the generic model.

### 10.1 Domain concepts and relationships

| Concept | Required distinction |
|---|---|
| SoftwareProduct | Product/component identity, separate from a Git repository or optional C1 project view. |
| CodeRepository | An ingested source repository, not a C1 knowledge/security partition. |
| SoftwareRelease / SourceSnapshot | A release association and an immutable source state, pinned to actual source identity. |
| Capability | User-facing behavior potentially implemented across multiple products. |
| CodeSymbol | Qualified function/method/class or other symbol, separate from its occurrence in a particular snapshot. |
| InterfaceOperation | Explicit API/message/command boundary linking components. |
| TestCase | A test definition and its intended verification target. |
| TestRun | An observed execution with exact source/configuration, result, and evidence. |

Documentation and code reuse Documents, DocumentParts, Sources, and Evidence. A code excerpt preserves language, encoding/formatting, source path, and immutable snapshot/range or digest where authorized.

Distinguish `documents`, `implements`, `defines`, `references`, declared/static `calls`, interface mapping, `verifies`, and observed execution. Names alone do not establish an integration or a call. A static edge is not proof that a path executed at runtime. Preserve tool/method provenance and unresolved relationships.

A function name is not globally unique. A mutable branch URL is not immutable evidence. Renames/refactorings may require explicit resolution; never merge unrelated symbols merely because their names match.

### 10.2 Target-version sets

Software context MUST select a declared target set identifying each relevant product/source snapshot, interface-contract version, and relevant configuration. Keep that set separate from the C1 knowledge revision and from current authorization.

Do not silently combine installed-release documentation, development-head implementation, and a test run from another version. A branch selection must resolve to a fixed source snapshot for the request. Unknown compatibility remains unknown. Availability of a newer snapshot does not change a pinned request.

For support, use the installed/reported target when known. For coding, use the actual development target. Defaults may be explicit and reported, never guessed from an undefined “latest.” Documentation can be applicable to a target even if its publication date is older than another guide.

### 10.3 Ingestion contract and coverage

Humans, deterministic importers, indexers, CI systems, and external agents populate C1 through the same authenticated APIs and ChangeSets. C1 does not need to run them.

An import records producer/tool identity and version, source repository and snapshot, analyzed scope, content identity/digest where supplied, supported analysis kind, errors, unresolved references, and completion/coverage state.

Repeated identical imports are idempotent within the declared producer/snapshot contract. Another producer's competing extraction retains its own provenance. Partial runs must not delete absent records as though a complete snapshot had been processed. Failed files do not prove an absence of dependencies. Previously extracted data may remain historical but must not be relabeled as analysis of a new snapshot.

Coverage metadata is itself authorized. Report incompleteness only within the caller's permitted view; do not disclose hidden repository paths, file counts, or restricted dependencies through an import report.

External format candidates include SCIP for symbol/index information and OpenAPI/AsyncAPI for declared interfaces. Selecting exact versions, language coverage, and mapping subsets belongs to M08. No mandatory all-language importer or runtime plugin system is implied.

### 10.4 Four roles of evidence

Keep these roles explicit in records and context presentation:

- **Normative:** documented intended behavior or an accepted contract.
- **Structural:** source text or a declared/static extraction about implementation.
- **Interpretive:** an attributed human/agent explanation derived from sources.
- **Observed:** a specific test/runtime result for a declared target and environment.

No role is universally equivalent to truth. A passing test checks its particular conditions, a test file is not a run, and an implementation defect must not silently redefine the expected contract.

### 10.5 Applicability and relative obsolescence

Documentation applicability relates a document/part version to a target set, with attributed evidence and review status. At minimum distinguish verified/applicable, requiring review, and explicitly non-applicable or contradicted where evidence supports that conclusion; exact enum names belong to M11.

A document may be correct for A1/B1 and outdated for A2/B2. Different parts may differ. A dependency change can deterministically mark a review candidate, but does not prove that prose is false. An attributed review or matching test can establish a specific discrepancy.

A new draft retains old history, selected target versions, source lineage, unresolved differences, audience restrictions, and publication state. A C1 commit does not merge a Git pull request or update externally maintained official documentation. Official external publication is recorded only from an explicit corresponding result.

<a id="11-software-agent-workflows"></a>

## 11. Software-agent workflows

All four profiles below are declarative Context Builder behavior, not separate LLM agents, separate databases, or permission grants. An external agent chooses its task and assesses whether the returned evidence is sufficient.

### 11.1 `test-development`

Return applicable requirements/contract excerpts, the target symbol and relevant implementation, necessary available types/interfaces, side effects/errors, existing tests/fixtures, execution instructions from attributed sources, and observable outcomes. Include code and text where stored and authorized instead of requiring repeated lookup of IDs.

Keep normative expectations distinct from actual implementation. A deliberate discrepancy in the fixture must remain visible; do not copy an implementation bug into a conformance-test oracle. Characterization of current behavior and conformance to a requirement are distinct declared goals.

A TestCase without a matching TestRun is a definition, not a success. A run on another commit/configuration does not verify the target. Mocked Software B is not evidence of a real A–B integration run. External execution may submit results; C1 does not execute arbitrary test commands from ingested files.

### 11.2 `support-documentation`

First return applicable documentation, prerequisites, procedures, configuration, limitations, and relevant known warnings. Prioritize target applicability and explicit reliability/review metadata before mere recency. A newer guide for another release must not silently replace the applicable guide.

Known authorized contradictions/applicability warnings must not be concealed simply because this is documentation-first. The profile does not assert that every problem can be answered from documentation.

### 11.3 `support-implementation`

A second explicit request targets the gaps the consumer identified, such as retry, timeout, error handling, or configuration. Return only the relevant permitted code/test/interface paths and necessary context. Preserve the same source target set and selected C1 snapshot as the first request unless the caller explicitly refreshes them.

C1 can report missing requested structured aspects but must not run an internal model to judge free-text answer sufficiency or launch an autonomous fallback. Documentation-only credentials do not acquire code access by selecting this profile.

Label official guidance, implementation evidence, interpretations, and observed results distinctly. Code evidence is not automatically a supported customer procedure. Source-read rights and customer-facing publication rights remain separate.

### 11.4 `documentation-update`

For a capability spanning two products, return the existing document structure and applicable parts, selected A/B implementations, explicit interface contract and responsibility split, relevant configuration, matching tests/runs, known changes/discrepancies, and unresolved compatibility.

The external author can submit a revised draft through a ChangeSet. Preserve per-part applicability, provenance, source revisions, and audience. Do not replace old-version validity with a global obsolete flag, erase unresolved contradictions, or mark a draft officially published merely because it was stored.

Before final approval/publication, a changed intended source target requires applicability revalidation. Sharing one canonical feature across products is not evidence that every pair of their releases is compatible.

### 11.5 Protected source handling

Complete source units are returned only when complete and authorized. Partial units are explicit excerpts, not silently executable reconstructions. Hidden content must not be inferred from default gap markers, line counts, or citations.

Comments, READMEs, command examples, and ingested documentation are untrusted content. They cannot override system/development instructions, trigger command execution, fetch arbitrary URLs, or grant access. Public fixtures contain synthetic data and no company secrets.

<a id="12-acceptance-scenarios-a01-a22"></a>

## 12. Acceptance scenarios A01–A22

The following are required observable outcomes, not claims of existing tests. `PLAN.md` maps them to named milestone checks. Each test uses synthetic fixtures, exact expected results, real services where integration guarantees are involved, and PASS/FAIL/NOT_RUN evidence.

### A01 — No-AI operation

With AI credentials absent and provider egress blocked, bootstrap the instance, principals, and policies without creating a workspace. A human and a deterministic API client can complete schema setup, entity/evidence creation, review/apply, queries, history, export, document reconstruction, and required context profiles. No model download or AI configuration appears in a mandatory path.

### A02 — Client parity

The UI and a conventional client perform equivalent writes through the same validation/review API. Expected records and permissions match; authenticated actor attribution correctly differs. There is no privileged UI-only bypass.

### A03 — Keyword contract

Verify case/whitespace/Unicode normalization, phrases, language tags, duplicate coalescing, ANY/ALL, empty filters, combined type/property/relation filters, stable ordering and pagination. Exact keyword semantics remain unchanged by topic profiles.

### A04 — Identity and resolution

Rename without ID change, leave an ambiguous alias unresolved, perform reviewed merge and split/undo with explicit reassignment, and inspect earlier history. Preserve current permissions and do not expose inaccessible duplicate identities.

### A05 — Conflicts without false exclusivity

Import two incompatible claims with distinct evidence plus a legitimate multi-valued relationship. Keep all claims, flag only the declared conflict, and show authorized competing values without treating two legitimate targets as incompatible.

### A06 — Time dimensions

Use two content snapshots and two world-valid intervals to produce distinct `valid_at` and `known_at` answers. Preserve unknown/year-only precision; never fabricate exact dates or substitute recording time for validity.

### A07 — Atomic retry-safe writes

Invalid references or failed operations write no partial batch. Concurrent writers on one base cannot lose an update. Identical retries produce one committed operation/receipt; different payloads under the same idempotency key fail. Lost responses and crash/restart reconcile the real outcome.

### A08 — Permission separation and review

A reader cannot propose; a contributor cannot apply without a separate grant; a reviewer cannot grant roles. Schema and access administration require distinct permissions. Creation checks the target scope. Independent review rejects self-approval when configured. Operational ownership does not silently read protected content.

### A09 — Resource isolation

Within one repository, guessed IDs, hidden edges, counts, drafts, errors, exports, cursors, and histories do not disclose unauthorized resources or relationships. Project membership grants nothing. Revoked clients cannot reuse old links/caches or route requests to another backend/deployment.

### A10 — Independent interoperability

Round-trip the supported JSON-LD/RDF profile through an independent processor and backend mapping. Preserve IRIs, typed/language-tagged literals, assertion identity, qualifiers, and provenance. Unsupported constructs produce explicit diagnostics without partial persistence or remote-context fetches.

### A11 — Schema and restore

Add a supported domain type without changing core application code. Reject incompatible changes without a migration plan. Restore old knowledge through a new reviewed change while preserving current grants and bindings. Project/scope changes do not alter IDs.

### A12 — Recovery and fail-closed operation

Restore documented knowledge/security backups in an isolated environment and reconcile incomplete operations before traffic. Verify current-policy behavior and repeat the no-AI workflow. Missing/untrusted identity or authorization fails closed; an old security backup is not silently assumed current.

### A13 — Multi-company address book

Create Company A, Company B, one shared Person, at least three principals, shared business details, an A-only note, and a selected-user phone assertion. Lookup, traversal, history, counts, and export return exactly the permitted subset without company workspaces or copied Person identities.

### A14 — Scoped document reconstruction

Create at least five ordered parts across three AccessScopes and two reader populations. Verify exact differing reconstructed views, no hidden-part effect on search/counts/metadata, immediate subsequent-request revocation, and current part-policy bindings on old document revisions.

### A15 — Cross-project context reuse

PaperTrader and Robotelier clients contribute to one canonical Tesla company, a separate financial instrument, and illustrative Optimus/vehicle/Megapack product/battery versions. A third client requests battery context anchored to Tesla without selecting projects. At least one battery lacks a Tesla keyword but matches an approved typed path. Include a duplicate source, conflicting claim, incomplete measurement, irrelevant product, and hidden connecting relation. Return usable facts/excerpts/citations and caveats, not merely IDs; exclude unrelated/hidden material, preserve exact keyword semantics, and declare budget truncation. All technical values are synthetic.

### A16 — Current binding regression

Keep a user in the former shared scope while moving a resource and DocumentPart to a restricted scope. Current, history, context, and export requests remain denied even when old content stores the shared scope. Restore cannot reactivate the old binding. Interrupted re-scoping and security-service failures fail closed.

### A17 — Multi-scope atomicity and neutral views

One ChangeSet affects resources referenced by two projects under different scopes. It commits only when every operation is authorized; otherwise none commit. Adding references to a visible view neither copies nor exposes hidden resources. Concurrent writes do not lose updates.

### A18 — Coding-agent test context

For a documented capability, return target-pinned requirements, relevant code, interfaces, fixtures, nearby tests, and cited execution instructions. Include a deliberate implementation/contract discrepancy and preserve it. Distinguish TestCase from TestRun and mocked from real integration. An external synthetic test can reproduce the predetermined defective/fixed fixture outcomes; C1 itself neither writes nor executes the test.

### A19 — Two-stage support

Applicable documentation answers only part of a requested aspect. A second explicit targeted code request uses the same target set and snapshot, even after newer versions are ingested. Label evidence roles and warnings correctly. Documentation-only credentials cannot gain code access by choosing another profile; no internal sufficiency model or autonomous fallback runs.

### A20 — Cross-software documentation update

A feature spans two products and an explicit interface. Existing documentation is valid for A1/B1 but one part is obsolete for A2/B2. Context includes both responsibilities, contract, applicable source/test evidence, and differences. A revised externally authored draft retains target lineage, old history, uncertainty, and audience. A dependency change marks review need, not automatic falsehood. C1 storage does not imply external publication.

### A21 — Source-version consistency and coverage

Two synthetic source repositories have multiple snapshots, a partial import, and unresolved relationships. All selected code/contracts/docs/runs correspond to the explicit target or are clearly qualified; incompatible/unknown combinations never masquerade as coherent. Failed extraction is not dependency absence; old extraction is not relabeled as current. Source locators stay immutable when branch names move.

### A22 — Code privacy and publication boundaries

Current policies protect code, snippets, snapshots, coverage metadata, source citations, drafts, and review reports, including history. Restricted/partial code is not presented as a complete executable unit. A read-authorized agent cannot automatically publish derived material to a broader audience. Unauthorized broadening is rejected or remains unpublished pending explicit review. Stored commands/markup never execute as a consequence of retrieval.

<a id="13-delivery-and-verification-discipline"></a>

## 13. Delivery and verification discipline

Use the existing M00–M13 roadmap; every milestone is planned independently. The original broad phases remain foundations, durable knowledge, context/software workflows, and Explorer/operational acceptance. This specification does not pre-authorize later milestones.

| Acceptance coverage | Primary roadmap ownership |
|---|---|
| Baseline and feasibility | M00–M01 |
| Model, standards, identity, security | M02–M03 |
| Changes, queries, directory, time | M04–M05 |
| Scoped documents | M06 |
| General context / A15 | M07 |
| Source versions and coverage / A21 | M08 |
| Test context / A18 | M09 |
| Support context / A19 | M10 |
| Documentation context / A20 | M11 |
| Human/API parity | M12 |
| Full A01–A22 and G1–G9 verification | M13 |

Security and no-AI regressions apply to every exposed feature, not only M13. Real backend/security integration is required for transaction, permission, and recovery claims; mocks are insufficient evidence for those guarantees.

M00 validates these local documents and their accepted extension rather than accessing Google Docs. It still needs its own plan, harness, and report; the existence of local source files does not mark it complete.

Exact service versions, language/framework, binding-publication protocol, query compilation, policy/cursor generations, normalization form, order keys, source-format subset, and benchmark thresholds remain explicit milestone decisions. An inability to prove a requirement blocks dependent implementation or requires an owner-approved change; it does not authorize silently dropping the test.

<a id="14-source-basis-and-public-technical-references"></a>

## 14. Source basis and public technical references

### Local provenance

This edition preserves the requirements of the original project specification v0.2 and associated architecture v0.2, followed by the software-code/documentation extension incorporated in `AGENTS.md` and `PLAN.md`. The source-document revision recorded when those files were prepared was:

```text
ANLCKQkD89hnI-0XryiImiiO8yvhoUseyovja35ppyfl8AmQjIBn_AU-aVvDOUS0K7P60fBKlXedaakqzyvt0A
```

Original source labels were “C1 project specification” and “MVP architecture” in Todo. They are historical attribution only. All required product content is stated here and in the local companion architecture. No unseen chat addendum or cloud document is part of the implementation dependency chain. This delivery does not alter Todo or claim a published cloud v0.3.

### Public references, not private requirements

The following are vocabulary/protocol references and implementation-research starting points. Product requirements do not require access to the original planning location. Pin actual dependency and standard-profile versions during implementation.

- [RDF 1.1 Concepts](https://www.w3.org/TR/rdf11-concepts/)
- [RDF 1.1 Schema](https://www.w3.org/TR/rdf-schema/)
- [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/)
- [SHACL](https://www.w3.org/TR/shacl/)
- [PROV-O](https://www.w3.org/TR/prov-o/)
- [SKOS Reference](https://www.w3.org/TR/skos-reference/)
- [Dublin Core terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/)
- [OWL-Time](https://www.w3.org/TR/owl-time/)
- [Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) — selector reuse candidate for precise evidence.
- [SCIP](https://github.com/sourcegraph/scip) — external source-index interchange candidate.
- [OpenAPI specification](https://spec.openapis.org/) and [AsyncAPI specification](https://www.asyncapi.com/docs/reference/specification/latest) — external interface-contract candidates; select pinned subsets rather than relying on a floating latest version.

No product implementation, backend proof, security test, or milestone verification is claimed by this document.
