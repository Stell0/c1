# ADR-0006 — Canonical identifiers and storage namespaces

**Status:** M02 implementation decision under the owner's implementation request.
The owner explicitly approved the storage-context fallback on 2026-09-27,
as required by M02 §7.

## Decision

Use the owner-selected vocabulary namespace `urn:c1:ns:core#`, with extension
vocabularies under `urn:c1:ns:<profile>#`. Context identifiers identify bundled
versioned files; they do not instruct C1 to dereference a URN or URL.

Mint canonical resource identifiers from the configured instance base, resource
kind and UUIDv4. Names, projects, producer identity and historical policy hints
never enter that identity calculation. Imports preserve supplied absolute IRIs;
IRIs are inert data and are never executed or fetched by the model layer.
Duplicate candidates are informational and use only explicitly supplied visible
records. No merge or redirect is inferred.

The storage adapter maps a canonical UUID to the backend class/UUID document ID
and retains `canonical_iri` explicitly. Other named structural nodes use a stable
hash of their canonical IRI for the backend key and retain that IRI for exact
export. Backend schema names and document keys do not become public identifiers.
A data-only profile chooses fields and types; no profile may supply executable
hooks or validators.

Keywords, intervals, boundaries and selectors have named structural nodes in the
interchange graph because M02 rejects blank nodes. They remain separately named
storage documents to preserve shared references; literals are value subdocuments.
These storage records do not independently authorize content. M03 must enforce
resource ownership/bindings for every protected traversal.

## Backend proof and approved fallback

The pinned TerminusDB v12.0.7 rejected the schema context declaration
`c1: urn:c1:ns:core#` with HTTP 400 `api:PrefixDoesNotResolveError`. The same
`full_replace=true` request with the default backend context and a small Entity
class succeeded. The [official schema reference](https://terminusdb.org/docs/schema-reference-guide/)
describes its context URI grammar. This differs from RDF's general IRI space;
it does not invalidate the chosen public URN namespace.

Owner-approved bounded fallback: retain TerminusDB's default `@base` and `@schema`,
with its accepted RDF/XSD prefixes, and omit the unused `c1` backend prefix.
Canonical URNs remain unchanged in the public context and literal record fields.
Do not substitute an HTTP namespace for the owner's chosen canonical namespace.
The owner approved this fallback before the schema installation gate.

## Boundaries

Storage configuration is constructed by trusted installation code. An operation
cannot override its database, organization or endpoint. M02 offers internal
fixture tooling without a public HTTP API; authentication and current-policy
resolution are M03 responsibilities. Ordinary application writes will use the
M04 ChangeSet path. No unrestricted backend query method is exposed.
