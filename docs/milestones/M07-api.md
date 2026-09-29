# M07 context API

`POST /v1/context` is an authenticated, read-only request for deterministic context. It uses the same current-binding authorization and query selection as other C1 reads. It creates no ChangeSet and does not infer conclusions. It may use the configured C1 authorization and knowledge services; it does not fetch arbitrary source URLs or call a model/provider endpoint.

## Request

The body is strict JSON; unknown fields and invalid profile fields are rejected. Required fields are `profile`, `profile_version`, and `anchor`. `anchor` is either `{ "id": "<canonical IRI>" }` or `{ "label": "...", "language": "..." }`. `topics` accepts label strings, `{ "label": "...", "language": "..." }`, or `{ "id": "<Concept IRI>" }`. The profile version must exactly match one in the startup-loaded local catalog.

Optional selectors are `keywords_all`, `keywords_any`, `fields`, `project_ref`, and `revision`. Keyword term objects retain M05 exact ANY/ALL semantics. `project_ref` only narrows the result. `formats` accepts `markdown`, `structured`, or both and defaults to both. `budget` has `unit: "bytes"` and `maximum` from 2,048 through 524,288, defaulting to 65,536. `cursor` continues an earlier page.

Example:

```json
{
  "profile": "graph-context",
  "profile_version": "1",
  "anchor": { "label": "Tesla" },
  "topics": ["batteries"],
  "fields": ["capacity", "cycle_life"],
  "formats": ["markdown", "structured"],
  "budget": { "unit": "bytes", "maximum": 65536 }
}
```

The selected topic scheme and paths come from the named local profile. Alias resolution is exact after the configured local keyword normalization; it does not change ordinary keyword matching. Label resolution only considers readable records. An unreadable ID and a nonexistent ID have the same 404 response. A label with multiple readable candidates returns `outcome: "ambiguous"`; a missing or unresolvable label/topic returns `outcome: "unresolved"`, without producing a context package.

## Response

A resolved response contains `outcome`, `revision`, `bounds`, and the requested renderer fields. The structured package has interpretation, orientation paths, facts, excerpts, disagreements, gaps, source citations, bounds, and a `format_parity_digest`. Markdown is rendered from that same selection and emits the corresponding sections in a fixed order. Structured output carries values and qualification fields; it does not merely return IDs or links.

Fact units keep a node/predicate's claims, qualifiers, and citations together. Product, version, measured quantity, unit, conditions, and measurement date retain separate identities and claims. Every relation, measurement, evidence item, source, document, and part is independently authorized. A citation to document text is included only when the explicit readable Document-to-Source relation and the full evidence/part/source chain are readable and pass the M06 selector and version checks. Source versions remain distinct from document and evidence versions. Missing or hidden dependencies are omitted without a diagnostic that reveals their existence.

A requested field is reported as `not present in the returned material` when its predicate or required typed path does not occur in the authorized package. This describes the response only; it does not claim the value is absent from C1 or the world.

## Budget and cursor behavior

The byte maximum applies to the complete emitted Markdown UTF-8 body, including variable source text, gaps, bounds, footer, and the actual cursor token. The structured response mirrors the same page; its JSON wire encoding is not counted. The builder selects the longest contiguous prefix of complete evidence units that fits. It never splits a unit or its disagreement/qualifications. If no unit fits, it returns 422 `C1-CX-010` with `minimum_required`; it does not issue a zero-progress cursor. `bounds` reports the included and deferred unit counts, truncation, maximum, rendered byte count, offset, and continuation token.

The cursor is signed and principal-bound. Continuation rebuilds authorization and checks the complete semantic prefix and its relevant current bindings. A changed prefix or revoked access requires restart (409 `C1-CX-011`). Cursor bytes can differ because the token has an expiry and HMAC; deterministic comparisons concern selected content/order and decoded semantic bindings.

## Limits and failures

The profile cannot expand M05's traversal limits. Context has a 500-unit bound, a 4 KiB per-citation excerpt bound, and the configured request time limit. Invalid profile catalog state fails readiness with 503; there is no implicit-profile fallback. A selected profile version unknown to the catalog, an unknown field, or malformed request returns 400 `C1-CX-001` / `C1-CX-002`. A traversal/time exhaustion fails without returning a partial package as complete. No AI-provider credentials, model SDK, arbitrary source-URL fetch, or generated summary is involved.
