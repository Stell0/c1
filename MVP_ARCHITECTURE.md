# C1 — MVP Architecture

**Document edition:** Local source edition 1, consolidated on 2026-09-25.  
**Status:** proposed reference implementation; no implemented capability or passed test is claimed.  
**Required behavior:** [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md).  
**Execution rules and milestones:** [AGENTS.md](AGENTS.md), [PLAN.md](PLAN.md).

## 0. Authority and use without Google Docs

This document is the repository-local architectural source for C1. It consolidates architecture v0.2 and the subsequent software-code/documentation extension. The companion specification contains the complete requirements, including A01–A22. Nothing needed to understand this design is left in a private cloud document or an unseen conversation.

The companion specification controls required behavior. This file describes boundaries and proposed construction. A mechanism labeled proposed must be selected and verified in its active milestone; a diagram is not evidence that a backend supports a transaction or a security guarantee.

Earlier instructions in the scaffold to retrieve the source Google Docs are superseded by these local documents. In M00, establish and validate the local baseline, retain its attribution, and create the development harness. No connector or Google credentials are required. Each M00–M13 milestone still receives its own detailed plan before implementation.

Public standards and dependency documentation remain useful for actual implementation research. Exact versions, licenses, library APIs, and service capabilities must be checked when pinned; this architecture does not reproduce entire third-party specifications or claim those checks have already run.

### Contents

- [1. Decisions and boundaries](#1-decisions-and-boundaries)
- [2. Runtime topology and deployment](#2-runtime-topology-and-deployment)
- [3. Internal modules](#3-internal-modules)
- [4. Canonical representation and storage](#4-canonical-representation-and-storage)
- [5. Standards profile and validation](#5-standards-profile-and-validation)
- [6. Authentication and resource authorization](#6-authentication-and-resource-authorization)
- [7. Proposed API](#7-proposed-api)
- [8. Deterministic reads and history](#8-deterministic-reads-and-history)
- [9. Knowledge writes and security publication](#9-knowledge-writes-and-security-publication)
- [10. Documents and evidence](#10-documents-and-evidence)
- [11. Context Builder](#11-context-builder)
- [12. Software-source model and ingestion](#12-software-source-model-and-ingestion)
- [13. Task-specific software contexts](#13-task-specific-software-contexts)
- [14. Explorer](#14-explorer)
- [15. Operations and recovery](#15-operations-and-recovery)
- [16. Verification gates G1–G9](#16-verification-gates-g1-g9)
- [17. Repository layout and milestone decisions](#17-repository-layout-and-milestone-decisions)
- [18. Sources and public reference points](#18-sources-and-public-reference-points)

<a id="1-decisions-and-boundaries"></a>

## 1. Decisions and boundaries

Build one modular C1 application above existing open-source infrastructure. The application supplies the canonical model, constrained API, validation/review workflow, policy-aware reads, document assembly, and deterministic Context Builder. A basic browser Explorer uses the same API as humans, scripts, and external agents.

### Fixed product boundaries

1. **One shared knowledge repository per instance.** There is no mandatory Workspace object, workspace parameter, or per-project database.
2. **Independent authorities.** Knowledge/revisions, identity, and current authorization are not interchangeable.
3. **Canonical identity is project-neutral.** Project views can overlap without duplicating resources or granting access.
4. **Authorization is granular.** Assertions, relationships, evidence, source metadata, and document parts have independent current checks.
5. **No required AI.** No model, embedding, semantic/vector search service, AI key, or internal autonomous agent participates in mandatory paths.
6. **Ordinary knowledge writes are reviewed ChangeSets.** No importer, UI, or agent receives a privileged write bypass.
7. **Standards-first with explicit subsets.** The interchange model is not a claim of full RDF/OWL/SPARQL support by the backend.
8. **Context is prepared, not invented.** C1 selects and renders stored evidence; consumers perform reasoning, coding, support judgment, and authoring.
9. **Software context is a domain profile.** C1 does not become a compiler, universal indexer, test executor, or Git publication engine.

### Reference choices requiring proof

| Responsibility | Proposed component | Boundary |
|---|---|---|
| Knowledge and immutable history | TerminusDB open-source server | Canonical repository, not one database per project. |
| Identity | OIDC provider; Keycloak reference deployment | Human/service identity, not knowledge authorization inferred from token display fields. |
| Current policy | OpenFGA-backed authorization plane | Grants, memberships, and current resource-to-policy bindings. |
| Supporting durable storage | PostgreSQL where required by identity/policy services | No second knowledge graph or vector index. |
| Application | One modular API/service and basic web client | Concrete language/framework selected in M00/M01; Python with established RDF/SHACL libraries is a reference proposal. |

No TypeDB, Graphiti, Neo4j, Cognee, Jena projection, plugin loader, queue cluster, or additional graph store is required. Do not add one to bypass an unproven operation; document the blocker and obtain approval for any architecture change.

<a id="2-runtime-topology-and-deployment"></a>

## 2. Runtime topology and deployment

```text
Human browser                  Conventional client / external agent
      |                                         |
      +-------------- authenticated API --------+
                            |
                    C1 modular application
                            |
       +--------------------+---------------------+
       |                    |                     |
       v                    v                     v
 OIDC identity        Authorization plane     Knowledge services
 provider             OpenFGA                Query / Change / Context
       |                    |                     |
       +--- supporting -----+                     v
            persistence                      TerminusDB
                                             one repository
```

A TLS reverse proxy exposes only intended application and identity endpoints. Backend and supporting databases remain on private networks. Clients do not call TerminusDB or OpenFGA directly and never receive their credentials.

The reference deployment can run a local identity provider and authorization services. Existing compatible services may be reused, but the supplied self-hosted configuration must not depend on a paid provider.

Begin with one C1 application instance and one writer. Multiple users, projects, source repositories, and AccessScopes are supported. Horizontally replicated writers and distributed orchestration are not MVP requirements.

The service endpoint selects one trusted instance configuration. A request cannot route itself to a different knowledge database. When separate customers require independent administration, use separate deployments with distinct credentials, data/security stores, routes, and backups. A shared installation is not a security boundary against its own infrastructure operators.

<a id="3-internal-modules"></a>

## 3. Internal modules

These are module boundaries in one application, not mandatory microservices.

| Module | Owns | Does not own |
|---|---|---|
| HTTP/session/API | Request envelopes, identity integration, limits, errors, response metadata. | Domain inference or caller-selected backend routes. |
| Authorization | Current principal rights, resource bindings, scope operations, authorized selection plans. | World facts or historical permissions read from content. |
| Model/catalog | Canonical IDs, profiles, record semantics, keyword/time conventions, profile validation. | Arbitrary executable schema extensions. |
| Change service | Drafts, review, base revisions, application receipts, idempotency, corrections. | Implicit access grants or Git merges. |
| Storage boundary | Tested TerminusDB operations and canonical-storage mapping. | Product semantics defined only by backend behavior. |
| Query service | Bounded predicates/traversal over explicit content revisions and current authorization. | Raw query execution for arbitrary client text. |
| Document service | Ordered permitted content and exact-source/excerpt representation. | Binary office rendering or browser-side redaction of already delivered secrets. |
| Context Builder | Task/profile selection, grouping, excerpts, citations, budgets, Markdown/structured rendering. | Novel conclusions, LLM summaries, or answer-sufficiency decisions. |
| Import/interchange | Normalization, supported JSON-LD, validation reports, ChangeSet proposals. | Arbitrary URL fetches, compiler execution, or autonomous research. |
| Software profile support | Source targets, applicability/coverage, task profiles as data. | A new software-specific backend. |
| Explorer | Accessible forms and read/review workflows over the API. | Privileged frontend-only operations. |

A context package uses the query and document services; it does not query the database through an alternate unprotected path. Domain-specific examples and profiles are data. Development agent roles in AGENTS.md are not runtime services in this diagram.

<a id="4-canonical-representation-and-storage"></a>

## 4. Canonical representation and storage

### 4.1 Public model versus backend records

Maintain separate, versioned artifacts for the public RDF/JSON-LD profile, validation shapes, and backend document schema. The mapping must be tested in both directions. A backend document syntax must not be advertised as supporting every JSON-LD feature automatically.

Proposed backend record families:

```text
EntityRecord             AssertionRecord          SourceRecord
EvidenceRecord           DocumentRecord           DocumentPartRecord
ActivityRecord           ResolutionRecord         SchemaProfile
ChangeSetRecord          Validation/ReviewRecord  ApplyReceipt
```

Software products, snapshots, symbols, interface operations, tests, coverage, and applicability fit the generic entity/assertion/document model under the software profile. They need not become extra mandatory core storage engines or a table for every domain type.

Store resource references unambiguously and preserve literal datatype/language. Each relationship assertion has its own identity and authorization binding. If a derived current-view edge is materialized, it must retain the supporting assertion IDs and remain governed by their visibility. A shortcut edge cannot bypass checks on the claim that created it.

### 4.2 Canonical identity

Assign immutable instance-level identifiers and canonical IRIs. Names, aliases, projects, producers, and policies are attributes/associations, not identity keys. A visible Tesla company can be reused by PaperTrader and Robotelier; its financial instrument and product/component versions remain distinct related entities.

Exact alias/ID lookup does not establish global uniqueness of names. Merge/split actions have explicit reassignment and policy preservation. Historic redirects are not authority to read an inaccessible canonical target.

For source code, separate logical symbol identity from snapshot occurrence. A qualified source symbol and its occurrence can be related explicitly; cross-refactoring continuity is not inferred from a bare name or digest alone.

### 4.3 Security references in content

The effective resource-to-policy binding lives in current security state, proposed as a relation in the OpenFGA-backed model. Content records can retain historical scope annotations for provenance or a validated projection, but those fields are not authoritative for any current or historical read.

Retain current binding/deny records for resources that survive only in history. A historical import/export or knowledge restore cannot reinstate old grants. A missing or inconsistent binding blocks access.

Explicit security inheritance can use a current authorization relation to a parent/default policy. It must not follow an arbitrary historical `partOf`, `worksFor`, or project-membership edge. The selected representation and invalidation semantics are M03 decisions.

### 4.4 Knowledge head versus workflow bookkeeping

TerminusDB is proposed for versioned content, but the exact supported operations must be proven on the selected open-source release. WOQL/GraphQL or backend document features are implementation tools, not the public C1 contract or a promised unrestricted SPARQL service.

Define separately:

- **Knowledge revision:** the immutable content snapshot selected by a query or ChangeSet base.
- **Backend commit:** a physical backend revision, whose relationship to public knowledge revisions is documented.
- **Workflow revision:** edits to drafts, validation reports, approvals, and operation state.
- **Security state/generation:** current grants, memberships, resource bindings, and pending transitions.
- **Source snapshot:** an imported Git/content revision, unrelated to the other revision counters.

Writing a validation report or approving a proposal must not accidentally invalidate that proposal's own intended base. An actual competing knowledge change must make the old base stale. M01/M04 must select and prove a bookkeeping arrangement that satisfies both requirements.

An internal protected namespace or backend-supported branch may be evaluated, but do not assume transactions across branches or stores. Do not introduce an unapproved second knowledge database to evade this proof. The storage location and recovery contract of durable security journals are likewise selected in M01/M03.

<a id="5-standards-profile-and-validation"></a>

## 5. Standards profile and validation

Use established libraries for RDF/JSON-LD processing and SHACL. RDFLib and pySHACL are reference candidates for a Python implementation; pin versions, actual dependencies, and licenses during the relevant milestone.

The supported semantic profile uses RDF 1.1 resources/literals, JSON-LD 1.1, RDFS, SHACL, PROV-O, and appropriate topic/time vocabulary. Use SKOS only for declared controlled concepts and labels, not as automatic synonym discovery. Use Dublin Core topic metadata and OWL-Time where their meanings fit.

Represent an assertion as a named RDF statement with subject, predicate, object, evidence/provenance, and qualifiers. Its existence does not automatically assert the underlying proposition into a selected-current graph. Several sources can reify the same or incompatible propositions without losing identity.

Use PROV entities for immutable evidence/record versions and activities for creation, import, review, or derivation. Distinguish an original document from repeated importing agents. Custom C1 vocabulary is limited to documented gaps such as workflow, review state, and profile semantics.

Start with a documented SHACL subset for required fields, types, cardinality, and allowed values. Unsupported constructs fail explicitly. Validate record structure, not source truth. Conflicting claims do not fail merely because a current-view predicate is normally single-valued.

Bundle/pin allowed JSON-LD contexts. Do not fetch arbitrary remote contexts or URLs while normalizing inputs. Handle blank nodes only through a documented deterministic normalization or explicit rejection. Public exports must round-trip through independent tooling for the supported subset.

No full OWL inference, public unrestricted SPARQL, raw SPARQL UPDATE, SPARQL federation, or RDF 1.2-only syntax is required. Optional future capability is not an MVP dependency.

For source ranges, W3C Web Annotation selectors are a reuse candidate. For software artifacts, SCIP and OpenAPI/AsyncAPI mappings are candidates evaluated in M08. A contract artifact describes a declared interface; it does not alone prove implementation conformance or deployed compatibility.

<a id="6-authentication-and-resource-authorization"></a>

## 6. Authentication and resource authorization

### 6.1 Identity boundary

Use an OIDC-compatible identity provider. Keycloak is the reference self-hosted choice, not a proprietary C1 login mechanism. The proposed browser flow is authorization code with PKCE and secure server-managed sessions. External clients use appropriate OAuth access tokens for the API.

Validate signature, trusted issuer, audience, expiry, and intended token purpose using established libraries. An ID token is not a general API access token. Do not store secrets in browser-accessible storage, query strings, audit output, or exported knowledge.

Service agents get separate identities and minimal resource/operation grants. A user-supplied delegation field cannot impersonate another principal. There is no global privileged AI account.

Any development bypass must be explicitly development-only, loopback-bound, and disabled in production. No-AI operation does not permit unauthenticated production access.

### 6.2 Current policy model

Use one authorization model/store for the shared instance. Do not create a project-specific store when decisions need to span shared resources. Pin the model version used by deployment.

Model instance-level schema/access/operational administration separately from resource/scope read, create, contribute, and review/apply rights. Operational ownership is not a hidden content-read bypass. AccessScope is reusable policy, not ownership of a resource's identity.

For each request, evaluate:

```text
trusted principal
  + requested operation
  + stable resource identity
  + CURRENT resource-to-policy binding
  + CURRENT grants/memberships
  + validated request context
  => authorized or denied
```

A known entity, both endpoints of an edge, or membership in a project does not automatically authorize associated assertions, relations, sources, or fragments. Explicit current inheritance is allowed; inferred inheritance from domain semantics is not.

Create permission authorizes proposing content for a target scope. It does not permit the client to install arbitrary OpenFGA tuples. Scope deletion or reassignment must account for current and historical-only resources. Inconsistent/multiple/unresolved bindings that violate the selected model fail closed rather than selecting the least restrictive interpretation.

### 6.3 Authorized selection and joins

The query service requires a current authorization plan before matching, counts, ranking, traversal, or assembly. A proposed small-MVP strategy is to obtain bounded allowed resource IDs, or an equivalently verified current-binding predicate, and apply it in backend query compilation.

Do not rely on scope IDs copied from an old content snapshot. Do not query everything, compute rankings/counts, then cosmetically remove forbidden rows. Every node and relation used to establish relevance must be permitted; source metadata and excerpts have their own checks.

If current-binding lookup or an authorization result set exceeds supported limits, fail explicitly or use a verified bounded continuation. Do not truncate the authorization set silently and claim complete query results. Precise query-planning and bounded-enumeration mechanics are M03/M05 decisions.

An optimized current-binding index is a security-sensitive projection, not a new source of truth. It cannot be used when stale or inconsistent. No performance optimization may fall back to historical scope annotations.

### 6.4 Revocation and request concurrency

Use fresh checks for apply, grant, revoke, re-scope, and protected continuations. Initially disable positive authorization caching or use the backend's verified higher-consistency path where available. Test actual selected-service behavior; do not assume a requested consistency mode creates a distributed transaction.

Subsequent requests after a completed restriction must use current grants and bindings. Long-running requests, in-flight revocation, response assembly, and publication races need explicit bounded behavior in M03. Already delivered bytes cannot be recalled. Bound response duration and avoid reusable public download URLs.

If a cursor contains authorization-dependent traversal state and policy changes invalidate it, require a safe restart. Opaque content revisions are not permission tokens. Current-binding tombstones protect resources retained only in history.

### 6.5 Declassification and audience

Changing to a broader or incomparable audience is a separately authorized security operation. Scopes are not assumed to form a total order; do not compute an invented “most restrictive scope” to justify publication.

A context assembled from readable sources may be delivered to that authorized caller. Persisting or publishing an externally derived answer/document to others requires separate target-policy authorization and the declared declassification/review workflow. Preserve derivation links; copying facts into a less-protected cache or draft cannot bypass this boundary.

This is an API/policy design, not a claim that C1 can infer all sensitive implications of arbitrary prose. The source/derived-content policy and residual risks must be documented rather than hidden behind a confidence score.

<a id="7-proposed-api"></a>

## 7. Proposed API

The following is a planning contract, not a list of existing endpoints. Select exact request schemas, field names, and response formats in the corresponding milestone and document them in OpenAPI. No endpoint requires a workspace selector.

| Method/path | Intended operation |
|---|---|
| `GET /v1/instance` | Authenticated non-sensitive instance/repository and supported-profile metadata. |
| `GET /v1/catalog` | Authorized types, predicates, constraints, schema/profile versions, and presentation hints. |
| `GET /v1/access-scopes` | Scopes the principal may know about. |
| `POST/PATCH /v1/access-scopes/...` | Authorized security administration, separate from content writes. |
| `POST /v1/access-scopes/{id}/bindings` | Proposed controlled current-binding assignment/reassignment operation. |
| `GET /v1/entities` | Bounded ID/type/name/alias/keyword/property/state/time filters. |
| `GET /v1/entities/{id}` | Authorized identity/display data and permitted related references. |
| `GET /v1/entities/{id}/neighborhood` | Bounded permitted direction/predicate/depth traversal. |
| `GET /v1/assertions` | Authorized claims, qualifiers, evidence, and competing assertions. |
| `GET /v1/sources` and `/v1/evidence` | Source/evidence inspection under independent current policies. |
| `GET /v1/history` | Authorized history for explicit target resources and content revisions. |
| `GET /v1/documents` | Authorized document metadata. |
| `GET /v1/documents/{id}` | Compact authorized reconstruction at a selected revision. |
| `GET /v1/documents/{id}/parts` | Permitted part inspection without exposing the unrestricted manifest. |
| `POST /v1/context` | Read-only deterministic context selection and rendering. |
| `POST /v1/changesets` | Proposed knowledge operations against a base revision. |
| `POST /v1/changesets/{id}/validate` | Validate exact payload. |
| `POST /v1/changesets/{id}/approve` | Authorized exact-payload approval. |
| `POST /v1/changesets/{id}/reject` | Explicit review rejection. |
| `POST /v1/changesets/{id}/apply` | Recheck and atomically apply knowledge/receipt. |
| `POST /v1/imports` | Supported bounded interchange input producing a ChangeSet. |
| `GET /v1/export` | Authorized supported snapshot export, not full-history backup. |

Identity-resolution and schema operations use ChangeSets; convenience routes, if introduced, create that same workflow. Security re-scoping is not an ordinary patch to a versioned field. Caller-submitted security annotations do not become effective bindings.

Use standard HTTP semantics, ETag/If-Match where applicable, Problem Details errors, explicit schema/model versions, and stable cursors. Hidden and nonexistent resources should not become distinguishable through unauthorized error detail. Commands, credentials, and repository routes cannot be taken from untrusted payloads.

### Illustrative context request

This example communicates semantics only; the final JSON schema is selected in M07/M08.

```json
{
  "profile": "support-documentation",
  "profile_version": "fixture-1",
  "anchor_id": "urn:c1:fixture:capability:contact-sync",
  "target_set_id": "urn:c1:fixture:target:a1-b1",
  "knowledge_revision": "opaque-content-revision",
  "aspects": ["configuration", "timeout", "retry"],
  "formats": ["markdown", "structured"],
  "budget": {"unit": "bytes", "maximum": 24000}
}
```

The endpoint is read-only even though it uses POST for a structured query. The request does not authorize a model, target refresh, code fallback, repository routing, or broader data visibility. Budget units/numbers here are illustrative, not fixed release guarantees.

<a id="8-deterministic-reads-and-history"></a>

## 8. Deterministic reads and history

### 8.1 Read pipeline

1. Authenticate the principal and requested operation against the configured instance.
2. Resolve current grants and resource-policy bindings; build the authorized selection plan.
3. Capture one content revision, or validate the requested accessible snapshot reference.
4. Validate selectors, profile, datatype/time conditions, target set, and resource budgets.
5. Compile the bounded backend query with authorization constraints included.
6. Apply world-valid time and source-applicability conditions within that selected content.
7. Assemble only authorized facts/excerpts and render permitted metadata.
8. Return revision/profile/target information, match reasons, and declared truncation.

A stable sort and revision-bound cursor prevent ordinary new content from silently mixing snapshots across pages. Each page reauthorizes. Project filters are optional narrowing conditions. Unresolved aliases/topics return permitted disambiguation or an explicit non-guessing outcome.

### 8.2 Keyword and graph context

Generate normalized keyword values locally from a documented versioned function. Preserve original spelling and optional language tag. Exact ANY/ALL, empty filters, literal/prefix label search, and phrase behavior remain separate from controlled-topic resolution.

Graph profiles follow allowed typed paths, not indiscriminate nearest nodes. In the battery fixture, company → product → battery provides a reason to include a component without a Tesla keyword; financial instruments, unrelated products, and supplier-adjacent nodes are not automatically included. Readable endpoints connected only by a hidden assertion do not match.

Profile depth, node/time limits, ordering, and normalization are deterministic and observable. No automatic stemming, translation, synonym inference, vector similarity, or LLM reranking appears.

### 8.3 History and corrections

Select old knowledge by content revision but resolve each stable resource's current binding. Preserve denied/tombstoned historical-only resources. A user still in an old shared scope cannot use that scope from the old snapshot after the resource has become restricted.

Apply world-valid time separately. Preserve imprecise dates, unknown bounds, and strict-versus-unknown matching as specified. A Git/source snapshot is not the C1 revision or the world-valid interval.

A correction adds explicit revised/superseding evidence and rationale. A competing claim is not necessarily a correction. Restoring older content produces a new compensating ChangeSet while retaining current grants, current resource bindings, and independent review rules.

History views, diffs, validation results, global revision metadata, and commit receipts must not expose protected payloads or meaningful private change details to unauthorized callers. Snapshot identity is opaque; detailed revision inspection requires its own checks. Residual metadata/timing risks are recorded in the security plan, not dismissed by opaque IDs alone.

<a id="9-knowledge-writes-and-security-publication"></a>

## 9. Knowledge writes and security publication

### 9.1 Ordinary knowledge workflow

```text
propose against base_revision
    → validate exact payload
    → review exact payload
    → recheck current policy and base
    → atomic knowledge operations + receipt
    → reconcile/deliver committed outcome
```

A producer supplies structured operations; the server records the authenticated actor and request digest. Validate syntax, supported profile, references, temporal precision, conflict rules, and authority over every target. New resources require explicit create rights for the intended scope.

A reviewer must be able to inspect the full protected payload and review the relevant operations. Modifying a validated/approved payload invalidates its prior checks. Independent review applies when configured.

Apply obtains the repository write lock, rechecks current policy and expected knowledge head, and uses the proven atomic backend boundary. A stale base fails and requires revalidation; do not silently merge semantic conflicts. Cross-project/cross-scope changes are all-or-nothing.

Idempotency is bound to principal, repository, and payload digest. A durable receipt identifies the one committed result. On timeout, reconcile the receipt before retry. Do not report success before durable confirmation.

### 9.2 Initial write concurrency

Use one application writer with repository-wide serialization. Normal clients, importers, background tasks, and administrative workflows cannot bypass it. Direct backend access is limited to isolated development probes, operational recovery under its own procedure, or explicit fault-injection fixtures.

An actual competing content commit invalidates a stale proposal even if it came from another project. This is an intentional initial simplicity/throughput tradeoff; measure contention. Prove a native expected-head/transaction alternative before relaxing the single-writer restriction.

Schema/profile changes and dependent content must become visible together when required. Atomicity must be demonstrated on the actual release and chosen operations, not simulated with unprotected sequential writes.

### 9.3 No fake content/security transaction

OpenFGA and TerminusDB are separate authorities. This design assumes no distributed transaction between them. An atomic knowledge commit does not mean that content publication and all security updates are automatically atomic.

M01/M03 must define a durable, idempotent publication/re-scope protocol. A reference direction is:

- keep proposed new content and reserved identities unreadable while provisioning is pending;
- durably record the operation, expected content/base, intended binding, and recovery state;
- serialize relevant security mutations and publication through the single application;
- establish content and a valid current binding before allowing readers to observe the completed publication;
- block affected reads while a transition is inconsistent;
- reconcile pending operations before serving affected content after restart;
- retain security provenance without treating historical content annotations as authority.

The concrete order, journal location, gating primitive, and crash recovery rules are deliberately not asserted as already proven. Temporary resource grants, pending identities, and orphaned bindings must not disclose unpublished content or metadata. If the chosen mechanism cannot meet the specification, the dependent milestone is blocked until a bounded design change is approved.

### 9.4 Re-scoping

Re-scoping verifies authority over the resource and destination policy, including declassification for broader or incomparable audiences. Update effective current bindings through the security workflow; invalidate dependent current-binding projections/caches. A content audit annotation is not that effective binding.

A failed transition cannot fall back to an old permissive scope. Retain valid current deny/binding state for historical resources. Ordinary content import, restore, or project membership cannot activate a policy change.

Security membership updates and knowledge operations are independently audited. The implementation must test concurrent revoke/apply, lost acknowledgments, repeated operations, and recovery at every publication step.

<a id="10-documents-and-evidence"></a>

## 10. Documents and evidence

### 10.1 Storage and ordering

Document records contain stable identity and descriptive structure. Parts contain stable identities, document references, deterministic order keys, text/structured text, and optional parent parts. Current security bindings are resolved separately.

Choose order keys and supported nesting in M06. Preserve insertion order deterministically without assuming renumbering the whole document. Reject dangling references, cycles where nesting is supported, ambiguous ordering, and unauthorized moves without partial writes.

Declare text encoding, newline preservation/normalization, and digest rules. Exact-source claims must be checked against that contract. Avoid lossy pretty-printing when returning evidence or code excerpts.

### 10.2 Reconstruction

Retrieve the selected Document and only its permitted parts under current bindings, then assemble them in order. Hidden part payloads never reach the renderer/browser. Default compact output does not disclose omitted IDs, headings, positions, counts, or redaction markers.

A document read does not grant access to all parts. Part inspection cannot reveal the unrestricted manifest. Old content/order is combined with current permissions, not historical scope fields.

### 10.3 Source citations

A citation identifies a permitted source version and exact location where available. Useful stored excerpts are included in context. A mere URL is not verification and does not trigger a remote fetch.

Use immutable source versions/digests and supported selectors for quotations/ranges. Line/path metadata is also authorization-controlled. A moving branch is not an immutable citation target.

If only some code is returned, present it as excerpts. Do not create an apparently complete function by deleting hidden lines or imply that a fragment is executable. Completeness requires both a complete source unit and sufficient permission.

### 10.4 Rendering and imports

Escape labels, excerpts, code, and descriptions. Sanitized Markdown must not load unauthorized images/resources or execute scripts. Imported shell commands or README instructions are data, not permission to run anything.

Importers send content through the normal API and ChangeSets. They cannot specify arbitrary filesystem paths for the server, activate access tuples, or force URL retrieval. Binary attachments remain external references unless a later approved capability handles them.

<a id="11-context-builder"></a>

## 11. Context Builder

### 11.1 Responsibilities and execution

The builder is an internal deterministic module over the authorized query/document services:

```text
explicit selectors + profile + target + revision + budget
    → permitted anchor/topic resolution
    → bounded allowed paths
    → authorized assertions / source parts / test records
    → grouping and evidence-preserving deduplication
    → deterministic Markdown + structured package
```

A profile contains approved declarative selection/path/order/presentation data. It is not arbitrary executable code. Changing profile semantics is versioned and reviewed as required by its administration policy.

The builder can select and format evidence, expose stored conflict/applicability checks, and report missing requested fields. It cannot decide an arbitrary natural-language issue is answered, fabricate relationships, or write novel summaries through an LLM.

### 11.2 Package contract

| Field group | Output |
|---|---|
| Request interpretation | Resolved entities/topics, ambiguity, selected profile and explicit filters. |
| Reproducibility | Instance/repository, content revision, profile/schema versions, source target set. |
| Orientation | Human-readable identities, versions, context sections, and allowed relevance paths. |
| Evidence units | Self-contained assertions with available excerpts, sources, attribution, qualifiers, and conditions. |
| Disagreements | Competing authorized claims, declared checks, and unresolved differences. |
| Coverage | Permitted source coverage and requested fields missing from returned material. |
| Budget | Truncation, coherent deferred units, and reauthorized continuation. |

Markdown and structured data derive from the same selection. IDs accompany content rather than replace it. Cite original source versions separately from import actors. Duplicate ingestion can be grouped visually but not counted as independent corroboration or merged across policies unsafely.

Product/version/configuration and quantity/unit distinctions remain explicit. Do not make a single “efficiency” field from unrelated measurements or a single code fact from different source targets.

### 11.3 Budgeting and ordering

M07 selects deterministic ordering and a measurable budget unit. Prefer stable evidence units with their essential qualifications. If a unit cannot fit, defer it visibly within permitted metadata or return insufficient budget rather than presenting a misleading partial claim. A small budget must not hide conflicting evidence for a displayed claim.

Continuation binds the content revision and query/profile state but reauthorizes. Source target sets remain pinned. Requests with identical content, profile, inputs, and current security state should produce the same selected material and order; only declared volatile metadata may vary.

A missing result means missing from the authorized, selected, successfully available material. It is not proof that no such knowledge exists. Hidden data cannot influence ranking, gaps, path explanations, or completeness statements.

### 11.4 Cross-project battery fixture

Use one canonical Tesla company, a separate financial instrument, and synthetic versions of Optimus, a vehicle, and Megapack with battery components. Two producer clients contribute; a third asks for battery context without project selection.

Include a component with no Tesla keyword, duplicate source acquisition, conflicting measurements, missing unit/condition, an unrelated neighboring product, and a hidden link. The expected package covers the permitted relevant components, includes usable excerpts and qualifiers, and excludes the irrelevant/hidden path. No real Tesla technical specification is asserted by this fixture.

<a id="12-software-source-model-and-ingestion"></a>

## 12. Software-source model and ingestion

### 12.1 Software concepts as profile data

Define a software profile over the generic Entity/Assertion/Document model:

```text
SoftwareProduct    CodeRepository    SoftwareRelease    SourceSnapshot
Capability         CodeSymbol        InterfaceOperation TestCase / TestRun
```

Coverage, applicability, symbol occurrences, and target sets are profile concepts/records with explicit semantics. A CodeRepository is an ingested source, not a new C1 repository or security partition.

A capability can span two products and many symbols. A code function is not automatically the product feature. Separate logical identity from definition/reference occurrences at immutable snapshots. A shared unqualified name does not establish identity, calls, compatibility, or integration.

Relations identify their basis: declared interface, static extraction, attributed interpretation, or observed execution. A syntactic reference is not necessarily a runtime call; a stored TestCase is not a passing TestRun.

### 12.2 Target selection

Select a target set that fixes the relevant product/source snapshots, interface artifacts, and configuration. The C1 revision fixes what knowledge is available; the target set fixes which software state the request concerns. Current authorization is checked independently.

A proposed logical target representation includes:

| Element | Meaning |
|---|---|
| Product/source IDs | Which software and source repositories participate. |
| Immutable source references | Commit/content identifiers and optional release associations. |
| Contract identity/version | The interface artifact joining the two sides. |
| Relevant configuration | Feature flags/environment options needed to interpret the behavior. |
| Applicability evidence | What establishes or questions that the materials fit the target. |

Resolve mutable branch selections once to explicit snapshots and report the resolution. Do not silently substitute the latest known source. Unknown compatibility is not a valid combination inferred from timestamps. Expose only permitted target and coverage metadata.

### 12.3 External ingestion

External parsers/indexers, scripts, agents, or CI systems submit snapshot metadata, symbols, source parts, relationship assertions, test definitions/results, and coverage via the ordinary API. No internal compiler or model execution is required.

A source import records producer/tool version, source snapshot, input scope, emitted resources, errors, unresolved references, and completion status. Tie extracted relations to the specific snapshot/method. Different producers can contribute different assertions without destroying provenance.

Use idempotent producer/snapshot payload identity. A failed or partial run must not mark unprocessed dependencies absent or delete all records it failed to emit. Publish coverage accurately; old analysis remains old analysis. Decide incremental snapshot-completion and source-tombstone rules in M08.

Source/index data can be larger than a request; bounded batches are acceptable, but partial visibility/completion must be explicit. The presence of a newer source snapshot does not mean its whole analysis is ready. Do not claim complete company ingestion from a small fixture import.

### 12.4 Existing format reuse

Evaluate SCIP for symbol/index interchange, OpenAPI for HTTP operations, and AsyncAPI for message interfaces. Tree-sitter or language tooling can be external producers, not required runtime components of C1. Select the first supported fixture language(s) and a precise mapping subset in M08.

Map evidence to immutable snapshot, path, and permitted range/digest. Keep original source text separate from a generated explanation. Preserve format/version/method attribution and unresolved relationships rather than inferring stronger behavior than the tool reports.

<a id="13-task-specific-software-contexts"></a>

## 13. Task-specific software contexts

These profiles extend the generic builder; they do not change its authorization or no-AI boundary.

### 13.1 Test development

`test-development` collects applicable normative expectations, exact target symbols, relevant bodies and types, declared interfaces, errors/side effects, available fixtures, nearby tests, and attributed test execution instructions.

Preserve an implementation/requirement discrepancy rather than turning current code into the conformance oracle. A characterization request may intentionally describe existing behavior, but its purpose must be explicit. Distinguish TestCase from matching TestRun and mocked dependency from real integration evidence.

A synthetic external test runner can verify fixture linkage during development and import its result. C1 does not execute the stored commands. A consumer demonstration validates reproducible source context, not arbitrary LLM test-writing quality.

### 13.2 Documentation-first support

`support-documentation` selects target-applicable procedures, prerequisites, configuration, limitations, and known authorized warnings. Applicable reviewed guidance outranks a newer unrelated guide. A target-obsolete guide must not win merely because it is documentation.

If a consumer identifies a gap, it explicitly requests `support-implementation` with the missing aspects. Keep the same target set and content snapshot unless the caller deliberately refreshes. Retrieve focused relevant implementation/configuration/test paths, not a dump of all source code.

A newer source imported between the two requests must not silently change the fallback target. Selecting the implementation profile grants no code access. Display documentation, static code evidence, interpretation, and observed verification distinctly; implementation evidence is not automatically an official supported procedure.

C1 can report a missing requested structured aspect. It cannot judge arbitrary free-text sufficiency or autonomously escalate retrieval through an internal model.

### 13.3 Documentation across two products

`documentation-update` uses the shared capability as anchor and includes the old document structure/applicability, both products' relevant implementation, explicit interface mapping, responsibility split, configurations, matching test evidence, and known discrepancies.

Store applicability relative to the target and, where necessary, per DocumentPart. A guide can remain valid for A1/B1 while a section is obsolete for A2/B2. A source dependency change marks a review candidate under a declared rule; an attributed check establishes a specific contradiction. Do not mark all documentation false after every new commit.

An external author submits a revised draft through a ChangeSet with target/source lineage and audience. Preserve earlier versions and unresolved differences. If the intended target changes before approval, revalidate applicability instead of assuming the draft still fits.

If official documentation resides in Git, C1 draft/review and Git PR/merge are separate workflows. Only explicit imported publication evidence can record an external published state. A knowledge commit alone does not modify the source repository.

### 13.4 Output protection

All source, contract, test, coverage, and applicability records use current resource authorization. Partial code is an excerpt; hidden source cannot appear in browser/network payloads or citation expansion. Code read permission does not authorize customer-facing publication of its derived documentation.

A task profile is a retrieval policy, not a grant or executable prompt. Commands, comments, repository instructions, and Markdown inside ingested source material remain untrusted data.

<a id="14-explorer"></a>

## 14. Explorer

Serve the minimum web client from or alongside the modular application using the same API/session boundary. It shows connected instance, optional project filters, selected revision/target, pending changes, and uncertainty.

Required workflows include entity/schema forms where authorized, keywords/aliases, relationships, competing assertions, evidence, document views, history, ChangeSet preview/review, controlled access administration, and context preview. Software views use generic/profile-selected approved widgets; no privileged software-only backend is required.

No hidden content is sent to the browser for client-side removal. Validate permissions on every request, not only on button visibility. After a revoke/re-scope, subsequent fetches and old context/history links are reauthorized.

Use keyboard-accessible list/detail screens and safe rendering. Whole-graph visualization, dashboards, rich collaborative editing, and automatic natural-language answers remain excluded. A filtered neighborhood view is enough.

<a id="15-operations-and-recovery"></a>

## 15. Operations and recovery

### 15.1 Packaging and exposure

Use pinned OCI container images and a reproducible Compose-compatible reference deployment. Later NethServer 8 packaging is a target, not an existing module or additional MVP system requirement.

Document private networking, permitted external endpoints, persistent volumes, secrets/rotation, TLS, readiness, health, resource limits, and first-administrator bootstrap. No production default can silently bypass authentication or expose backend credentials.

No mandatory model SDK, AI provider configuration, embedding job, vector index, runtime plugin loader, extra graph database, or paid service is present. Supporting PostgreSQL holds identity/security-service state, not a second authoritative knowledge model.

### 15.2 Logs and operational records

Use structured protected audit logs for principal, instance/repository, operation, outcome, and correlation ID. Record schema/access/publication changes and recovery outcomes without bearer tokens or unnecessary source payloads. Operational records and full ChangeSet payloads are not generally readable merely because the caller can see one affected entity.

Measure request/node/response-size limits and write contention on stated fixtures and hardware. Bound operation duration and memory. Latency, scale, and source coverage are measured evidence, not implied by adopting a graph database.

### 15.3 Backup and restore

Separate authorized snapshot export from full repository backup. Snapshot export includes only the supported permitted graph/provenance/profile view; it is not a copy of history or the policy store.

Back up versioned knowledge, necessary workflow/recovery metadata, identity, and current authorization. A knowledge-only restore cannot restore old grants or bindings. Resources restored without valid current policy remain denied until safely provisioned.

For disaster recovery, restore into an isolated environment, verify security freshness and pending-operation reconciliation, test historical binding protection, and only then serve traffic. An older security backup requires an explicit operator procedure to reconcile subsequent revocations; it must not silently reopen access.

### 15.4 Failure matrix

| Failure | Required behavior |
|---|---|
| Identity validation cannot be trusted | Deny protected operations. |
| Authorization/current-binding service unavailable | Fail closed; no permissive snapshot fallback. |
| Backend timeout with uncertain apply | Reconcile receipt before retrying. |
| Invalid/mid-batch failed knowledge operation | No partial visible knowledge transaction. |
| Re-scope interrupted | Block affected reads until safe reconciliation. |
| New content missing valid current policy | Keep it unavailable. |
| Draft content changed after approval | Invalidate checks and require revalidation/review. |
| Cursor/target state invalidated | Reauthorize and restart/refresh explicitly; no silent mixing. |
| Source acquisition incomplete | Record partial coverage; no false absence or current-complete claim. |
| Unsupported schema/interchange | Explicit diagnostic; no silent semantic loss. |

Choose a durable recovery protocol before production reliance. Mock-only tests cannot establish these cross-service behaviors.

<a id="16-verification-gates-g1-g9"></a>

## 16. Verification gates G1–G9

Retain the existing gate identifiers. These are future proofs and integration tests, not completed evaluations. Early infrastructure probes do not discharge final application acceptance. The full A01–A22 register is in the companion specification, and detailed named checks remain in PLAN.md.

### G1 — Open-source edition and artifact boundary

Pin the exact TerminusDB and supporting artifacts, versions/digests, actual licenses, required notices, and operations used. Prove that the required path does not rely on proprietary/enterprise-only features. A project's name or marketing description is not license/capability evidence.

**Initial/final ownership:** M01 / M13.

### G2 — Atomic knowledge application

Prove all-or-nothing operations plus receipt, expected-base rejection, no lost updates, idempotent replay, lost-response reconciliation, crash recovery, and coordinated schema/data publication through the chosen API. Ensure workflow bookkeeping does not invalidate its own proposal while a competing knowledge commit does.

**Initial/final ownership:** M01, M04 / M13.

### G3 — Supported interchange fidelity

Round-trip resources, separate assertion identities, literal datatypes/languages, time qualifiers, source evidence, and provenance through independent RDF/JSON-LD processing and the storage mapping. Explicitly reject unsupported constructs and unapproved remote contexts.

**Initial/final ownership:** M01, M02 / M13.

### G4 — Shared-repository resource authorization

Exercise multiple principals, projects, and scopes in one repository without creating workspaces. Verify edge/endpoint independence, scoped creation/review, hidden-data noninterference in query outputs, cursor/history/export checks, token validation, service failure, and no project-derived grants.

**Initial/final ownership:** M03, M05 / M13; regression on every protected path.

### G5 — Scoped document reconstruction

At least five ordered parts across three scopes produce different exact expected views for two readers. Hidden payload and structure never reach rendering. Search/count/history/export and subsequent-request revocation remain correct. Code excerpts preserve source integrity without false completeness.

**Initial/final ownership:** M06 / M13.

### G6 — Multi-company shared identity

Two companies share one Person identity while common details, a company-private note, and a selected-user phone remain independently protected. Optional views do not duplicate identity or grant access. Lookup, traversal, history, and export preserve these outcomes.

**Initial/final ownership:** M05 / M13.

### G7 — Mandatory operation without AI

Run with AI credentials absent and provider egress blocked. Complete API/human knowledge workflows, document reconstruction, and all context profiles without model execution or downloads. Integration services remain locally available; no false claim of operating without identity/security infrastructure.

**Ownership:** every exposed feature, full release check in M13.

### G8 — Current bindings, publication recovery, and multi-scope guarantees

Move a resource/part from shared to restricted while a reader remains in the old scope. Deny current/history/context/export reads using old annotations. Preserve the restriction through restore and deleted-resource history. Inject failures into provisioning/re-scope and reconcile without leakage. Prove atomic multi-scope knowledge writes without claiming a shared OpenFGA–TerminusDB transaction.

**Initial/final ownership:** M01, M03, M04, M06 / M13.

### G9 — Consumer-ready context

Run the PaperTrader/Robotelier/Tesla fixture with a third consumer and no project selection or AI. Verify typed-path relevance, explicit ambiguity, source deduplication, usable assertions/excerpts, version/unit separation, conflicts, missing aspects, budgeted continuation, and per-path/evidence authorization.

Extend the same discipline to A18–A22: source targets and coverage, test-development evidence, documentation-first targeted fallback, cross-product documentation applicability, and publication/code privacy. These extend rather than replace the original battery fixture.

**Initial/final ownership:** M07 and M08–M11 / M13.

### Gate outcomes

A failed required proof blocks dependent implementation or requires an explicit owner-approved revision. Do not narrow scope silently, remove negative tests, introduce unapproved stores, or mark an unavailable test passing. Evidence identifies exact code/service versions, fixture, command, output, and PASS/FAIL/NOT_RUN status.

<a id="17-repository-layout-and-milestone-decisions"></a>

## 17. Repository layout and milestone decisions

### Proposed layout, not already-existing implementation

```text
AGENTS.md
PLAN.md
PROJECT_SPECIFICATION.md
MVP_ARCHITECTURE.md
docs/
  decisions/
  milestones/
    Mxx.md
    Mxx-report.md
src/
  model/
  api/
  authorization/
  changes/
  storage/
  query/
  documents/
  context/
  interchange/
profiles/
  core/
  software/
fixtures/
  core-knowledge/
  directory/
  scoped-document/
  cross-project-batteries/
  software-integration/
tests/
deployment/
web/
```

Concrete language/package names may change in M00 while preserving responsibilities. A profile directory contains declarative artifacts, not a plugin loader. Source fixture repositories are synthetic and are not infrastructure partitions.

### Milestone relationship

| Milestone | Architecture result |
|---|---|
| M00 | Local baseline, attribution, harness, and separate-plan/report conventions. |
| M01 | Actual backend/license/transaction/security feasibility; select risky mechanisms. |
| M02 | Canonical profile, validation, and storage/interchange mapping. |
| M03 | Current principal/binding policy boundary and recovery-safe security operations. |
| M04 | Reviewed atomic knowledge writes, receipts, corrections, and history. |
| M05 | Shared identity, directory fixture, deterministic bounded query API. |
| M06 | Ordered protected documents and source/excerpt integrity. |
| M07 | General deterministic Context Builder and cross-project fixture. |
| M08 | Software profile, immutable source targets, imports, and coverage. |
| M09 | Test-development context and external synthetic verification demonstration. |
| M10 | Two-stage documentation/code support context. |
| M11 | Cross-product documentation applicability, draft lineage, and publication separation. |
| M12 | Human Explorer over the same protected APIs. |
| M13 | Clean deployment, backup/restore, measured limits, complete acceptance. |

All start unimplemented; PLAN.md remains the execution roadmap. Only the owner-selected milestone is planned in detail. Authorization to create these files is not authorization to execute all milestones.

### Decisions deliberately left to individual plans

| Decision | Milestone boundary |
|---|---|
| Language/framework, bootstrap/check commands, code layout | M00 |
| Pinned service releases/licenses, exact transaction API, knowledge/workflow head strategy | M01 |
| Security operation journal location and content-policy coordination proof | M01, refined M03 |
| Supported JSON-LD/SHACL subset, blank-node policy, literal/normalization mapping | M02 |
| Exact OpenFGA model, inheritance/binding strategy, consistency, sessions, concurrency | M03 |
| ChangeSet wire schema, receipt/base semantics, migration boundary | M04 |
| Query compilation, cursors, bounds, identity merge mechanics | M05 |
| Document order/nesting, encoding, selectors, safe reconstruction | M06 |
| Profile grammar, deterministic ranking, budgets, citation/continuation encoding | M07 |
| Source format/language subset, symbols/occurrences, target sets, completion semantics | M08 |
| Test-context dependencies and fixture demonstration runner | M09 |
| Source priority, aspect-gap selectors, fallback continuation | M10 |
| Applicability states, review-candidate rules, external publication mapping | M11 |
| Frontend components, keyboard/browser verification | M12 |
| Final dependency pins, operational commands, recovery/benchmark thresholds | M13 |

Leaving these decisions explicit is intentional. The owner asked for separate milestone planning, not a fully invented implementation with unverified libraries and command lines. Every active plan must choose enough detail to implement its gate without weakening the required behavior.

<a id="18-sources-and-public-reference-points"></a>

## 18. Sources and public reference points

### Local attribution

The original architecture was v0.2 in Todo, read alongside the specification at source revision:

```text
ANLCKQkD89hnI-0XryiImiiO8yvhoUseyovja35ppyfl8AmQjIBn_AU-aVvDOUS0K7P60fBKlXedaakqzyvt0A
```

This local edition incorporates the later accepted software-context extension already carried by AGENTS.md/PLAN.md. It does not claim the source cloud document contained that extension or was updated to a new version. Original cloud identifiers are not execution dependencies. No private source needs to be opened during implementation planning.

### Public implementation references

These are research/standards entry points, not completed dependency verification or substitutes for requirements:

- [TerminusDB open-source project](https://github.com/terminusdb/terminusdb) and [documentation](https://terminusdb.org/docs/): verify selected edition, query/version APIs, and transaction behavior.
- [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html): identity protocol boundary.
- [Keycloak](https://www.keycloak.org/documentation): proposed self-hosted identity provider.
- [OpenFGA](https://openfga.dev/docs/): authorization-model, resource-relation, consistency, and datastore behavior to verify.
- [RDFLib](https://github.com/RDFLib/rdflib) and [pySHACL](https://github.com/RDFLib/pySHACL): candidate established processing libraries, subject to pins/license checks.
- [SCIP](https://github.com/sourcegraph/scip): optional external source-index input format.
- [OpenAPI](https://spec.openapis.org/) and [AsyncAPI](https://www.asyncapi.com/docs/reference/specification/latest): select pinned declared-interface subsets when needed.
- [W3C Web Annotation](https://www.w3.org/TR/annotation-model/): candidate precise evidence selectors.

The supported RDF/JSON-LD/SHACL/PROV/topic/time standards and their links are listed in PROJECT_SPECIFICATION.md. Exact dependencies and any additional required standards reuse are decided in the corresponding milestone, with primary-source evidence retained locally.

No software implementation, transaction proof, security guarantee, test execution, company-source ingestion, or release publication is claimed by this architecture document.
