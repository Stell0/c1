# M03 implementation contracts

These internal interfaces refine the authorized M03 plan; they are not public
knowledge APIs. Starting implementation: `7db3326`. Owner authorized M03 and
commit/push on 2026-09-27.

## Revalidation and security choices

- M02 is VERIFIED at `4be307f`. Its client has no historical reads: add a narrow
  configured-client `get(..., commit=...)` and `get_record(id, registry, commit=...)`
  using the M01-proven commit path. The current schema authority is still checked.
- A one-second token remains valid during D2's 30-second leeway. T01 must test
  expiry beyond that leeway, not weaken validation or assert expiry after 2 s.
  `exp`, `iat`, issuer, audience, subject and token purpose are required; `nbf`
  is validated if present (Keycloak may omit it). No untrusted claim chooses keys.
- Recovery rechecks current authority for the initiating actor and independent
  approvers before completing a pending security operation. Missing authority
  keeps affected resources denied. Every scope move requires explicit review.
- One writer lock covers all security mutations. Resource reads do not wait on
  it: they require stable current workflow revision before/after selection and
  reauthorize before returning content. A concurrent membership/binding change
  invalidates that selection. No positive authorization cache exists.
- Pending operations gate all affected resources before any cascade step.
  Journal transitions and binding changes are written together in one workflow
  transaction; knowledge and FGA are separately confirmed. No distributed
  transaction is claimed.
- Probe endpoints are disabled by default and restricted to synthetic records
  under `urn:c1:probe:`. They exercise security publication only. No general
  knowledge mutation endpoint or ChangeSet bypass is exposed.

## Shared Python interfaces

`config.Settings` is a frozen deployment-only dataclass, loaded from C1_* env.
Fields: `instance_id`, `instance_base`, `issuer`, `issuer_alias`, `audience`,
`fga_url`, `fga_token`, `fga_store`, `fga_model`, `terminus_url`,
`terminus_password`, `organization`, `knowledge_database`, `workflow_database`,
`lock_path: Path`, `independent_review=True`, `enable_probe_routes=False`,
`crash_after: str|None=None`. Secrets are excluded from repr. `from_env()` is the
only implicit environment loader; test constructors use explicit trusted values.

`authorization.principal.Principal`: frozen fields `issuer_alias`, `subject`,
`kind` (human/service); `.id` returns safe, injective FGA `user:alias.subject`
encoding. Raw subject retained separately. `TokenValidator(settings)` exposes
async `authenticate(token: str)->Principal`, `ready()->bool`, `close()`; errors
use `AuthenticationError` without token text. Cache JWKS keys only, never grants.

`authorization.journal.Journal(StorageConfig)` is an async context manager:
`initialize()` on a fresh isolated database, `get(kind,id)->dict|None`,
`list(kind)->list[dict]`, `save_many([(kind,id,payload),...], expected_head=None)`,
`head()->str`, `ready()->bool`. Kinds are Scope, Binding, Operation. Payloads are
operational JSON, not canonical knowledge records. It uses the configured
workflow database, a typed envelope schema and head-CAS writes; insert versus
replace is handled without losing existing records. No per-call DB routing.

Root owns `authorization/models.py`, `fga.py`, `bindings.py`, `plane.py`,
`operations.py`, `audit.py`. The FGA client uses the native model JSON file,
fresh Check and Read, 2 s timeout, chunked batch checks and no grant cache.

`api.app.create_app(settings, *, runtime=None)` creates the app; lifespan builds
and closes the runtime. `Runtime` (root-owned) contains `.settings`, `.tokens`,
`.plane`, `.operations`, `.journal`, `.knowledge`, `.fga`, `.registry` and exposes
async `.start()`, `.close()`, `.ready()` and `.read(principal,id,revision=None)`.
`runtime` injection is trusted test setup, never an HTTP parameter.

Plane methods return `Decision(allowed: bool, reason: str)`: `check_read(p,id)`,
`check_operation(p,op,id)`, `check_scope(p,op,scope_id)`, `check_instance(p,op)`,
`batch_read(p,ids)->dict[id,Decision]`, `bindings(id)->Binding|None`.

Operations async methods: `create_scope(p,label,id=None)`, `retire_scope(p,id)`,
`membership(p,scope,member,role,grant=True)`, `instance_grant(p,member,role,grant=True)`,
`provision(p,record,scope_id=None,inherited_from=None)`,
`propose_rescope(p,resource_id,to_scope)`, `approve(p,operation_id)`,
`apply(p,operation_id)`, `recover()` and `get_operation(p,id)`.
Methods return JSON-compatible dicts. `SecurityError(status, reason)` carries a
safe code only. The root will add a bounded probe revision method for T04.

Security request fields: scope `{label, id?}`; membership/instance grant
`{member, role}`; rescope `{resource_id}` at destination scope's `/bindings`;
probe `{record: NodeRecord, scope_id?, inherited_from?}`. Forbidden policy fields
in records fail validation. Identifiers in probe GET are percent-encoded paths.
Security administration offers scope DELETE and operation recovery POST in
addition to the routes enumerated in D9, needed by D7's existing contract.

API audit records have only correlation ID, principal, operation, target IDs,
outcome and reason; never token/request bodies/content. Client delegation is
ignored for identity, audited, and rejected where strict request shape requires.
