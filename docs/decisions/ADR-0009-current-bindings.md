# ADR-0009 — Current grants and resource bindings

**Status:** M03 implementation decision under the owner's implementation request.

## Decision

The bundled OpenFGA native JSON model is authoritative; matching `.fga` text is
human-readable documentation. The product uses the native HTTP API with HTTPX,
a two-second timeout and `HIGHER_CONSISTENCY`. The existing OpenFGA SDK remains
a development dependency for unchanged M01 probes.

Instance administration, scope reader/creator/contributor/reviewer/access_admin
and resource permissions are separate capabilities. Administrative ownership
never implies content access. Creating a scope grants its creator access_admin
only. Creating a resource requires creator or contributor in its destination
scope. A domain relationship or project reference cannot grant permissions.

Every read checks an active current workflow Binding, a known active Scope, no
pending operation affecting that resource or scope, exactly one OpenFGA
`bound_to` tuple matching the Binding, and a fresh permission check. Missing,
revoked, transitioning, inconsistent or unreachable state denies. Historical
knowledge uses these same current checks; stored scope hints are provenance.

BatchCheck uses chunks of at most 50 and still checks every current binding.
Failure falls back to sequential fresh checks, never cached allows. Workflow
revision checks surround authorization and content selection; a concurrent
official policy operation makes the read fail closed. Reads do not take the
writer lock. Already delivered bytes cannot be recalled.

Inheritance is materialized in workflow bindings. A reviewed rescope captures
its exact descendant set and bindings. A changed set is stale. Explicitly scoped
children are excluded. Scope retirement refuses any dependent Binding, including
tombstones, or any native `bound_to` tuple. Retired scope records remain durable.
Resource OpenFGA object IDs hash canonical IRIs; this backend encoding does not
change canonical knowledge identities.

## Evidence and sources

- [OpenFGA consistency](https://openfga.dev/docs/interacting/consistency)
  describes higher-consistency checks and cache behavior.
- [Check and BatchCheck](https://openfga.dev/docs/getting-started/perform-check)
  defines the native request/result contract and batch limit.
- [Relationship queries](https://openfga.dev/docs/interacting/relationship-queries)
  supplies tuple reads used for binding validation and retirement.
- M03-T02–T05 cover capability separation, independent resources, current binding
  at historical revisions, native batch decisions and injected binding faults.
  Additional plane and cascade tests cover revision races and stale approval.

Multi-host authorization coordination and readable-resource enumeration remain
outside M03. Direct administrative writes to backends bypass the single-writer
protocol and are not a supported product mutation path.
