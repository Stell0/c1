# ADR-0020 — Batched current-authorization verification

**Status:** Accepted for M09a implementation, 2026-10-01.
**Context:** [M09a plan](../milestones/M09a.md); ADR-0009 (current bindings); ADR-0013 (authorized selection); ADR-0017 (per-step decision memo, version-keyed journal listings).

## Decision

1. **Security views.** `Journal.view()` returns an immutable `SecurityView` built once per workflow data version from one listing. It holds bindings, scopes, pending operations indexed by target and by scope, and a flag for pending instance grants. Decision functions read the head, take the view, and deny with `security_revision_changed` unless `view.version` equals that head. They re-read the head after deciding, as before. `Bindings.get` and `Bindings.scope` return deep copies of view entries; administrative `Journal.list` callers keep receiving copies. *This refines plan D2: the hot paths no longer list or copy the journal at all, so the remaining copying callers are rare and are left unchanged.*
2. **One decision function.** `AuthorizationPlane.check_many(principal, ids, relation)` applies the ADR-0009 rules to every ID: an active binding and scope, no pending operation, exactly one matching live `bound_to` tuple, and a fresh permission check. It uses one view, one binding source, and BatchCheck in chunks of 50, falling back to sequential checks. Single checks (`_resource`, `check_read`, `check_operation`) call it with one ID, so reason codes are identical. `batch_read` calls it with BatchCheck for every chunk. Any exception denies the whole call with `security_unavailable`.
3. **Exact binding source.** `bound_to_many(fga, objects, binding_count)` reads per object (16 concurrent reads) or scans the whole store with `FGA.scan_bindings`. The pinned OpenFGA v1.21.0 rejects filtered bulk reads, so the scan reads without a tuple key. It keeps every `bound_to` tuple on `resource` objects, including tuples from unknown scopes. It fails closed on errors, repeated continuations, or more than 2,000 pages. The scan is used when `ceil(bindings × 1.1 / 100) + 1 < ceil(n / 16)`, that is, when it needs fewer sequential round trips. *This refines plan D4, which compared request counts.* The query planner calls the function directly with its index snapshot's binding count; the count travels to finalize on `AuthorizedPlan.binding_count`, through a request-scoped context variable.
4. **Catalog parse cache.** Trusted catalog profiles are parsed once per process, keyed by alias and the SHA-256 of the core and profile `profile.json`, `context.jsonld` and `shapes.ttl`. `load_candidate` returns private deep copies, because callers may extend a registry. Readiness detection uses the shared parses read-only and returns a copy of the selected registry. The installed schema and markers are still read freshly on every readiness call.
5. **No positive cache across requests.** Views, binding sources and decisions live within one decision call or one `_DecisionMemo` step.
6. **Gate environment (owner decisions during the makako gate).**
   - **Fixed Postgres address:** the development compose file pins Postgres to `10.89.250.10` on a fixed `10.89.250.0/24` network. OpenFGA and Keycloak use that address, because the makako Podman DNS resolver intermittently failed to resolve `postgres`.
   - **Short keep-alive expiry:** the TerminusDB clients (`c1.storage.terminus` and the M01 probe) discard pooled connections that have been idle for more than 1 s. Long runs had failed when a request reused a connection that the server was closing. The connection-reset failures were `httpx.ReadError` on read-only GraphQL queries, and `RemoteProtocolError` on a probe.
   - **Retry rule unchanged:** the owner kept M07 D21, so `ReadError` is still not retried.

## Consequences

- **Decisions:** decisions and error contracts are unchanged. A changed journal version detected by the view is a new, earlier `security_revision_changed` denial, which can only make a check stricter.
- **Unit-test seams:** fake journals used by plane tests now provide `view()`. Planner tests keep their three-argument `_authorize` seam.
- **Cost:** the remaining cost grows with the number of readable resources in OpenFGA BatchChecks, and with the whole store for scans. Very large stores fall back to per-resource reads under the round-trip rule.

## Rejected alternatives

- **Reading `bound_to` per known scope.** Rejected: it misses tuples from scopes the journal does not know, which M03-T05 requires to deny.
- **Positive decision caching across requests.** Rejected: forbidden by AGENTS.md §5.3 and ADR-0009.
- **Returning shared registries from `load_candidate`.** Rejected: a test exposed that callers extend returned registries, which would corrupt the cache.
