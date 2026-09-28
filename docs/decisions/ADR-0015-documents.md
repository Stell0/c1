# ADR-0015 — Scoped document order and rendering

**Status:** M06 implementation decision under the owner's milestone request.

## Context

A Document and each DocumentPart have independent current bindings. A reader's
document view must contain only readable parts, in deterministic order, at both
current and historical knowledge revisions. Text may contain arbitrary source
prose or code and must never become executable markup during server rendering.

The original M06 plan proposed a globally unique producer-supplied order key.
If a contributor can write to a document but cannot read one of its parts,
rejecting a guessed key only when it equals that hidden part's key discloses a
protected position. The failure is observable even when the error omits the
part ID. The roadmap's M06-T06 requires valid deterministic ordering, but does
not require unique raw rank strings.

## Decision

`c1:orderKey` is a 1–64-character rank over `0-9A-Za-z` and cannot end in
`0`. Equal ranks are valid; all projections sort by `(rank, canonical part
IRI)`. Invalid grammar and duplicate resource identities are rejected. A
producer may choose an intermediate rank using `between`; because the grammar
is finite, that helper raises when an interval is exhausted. It does not
renumber other parts. A stale ChangeSet is still rejected and must be rebased.

A part's content preserves its Unicode code points exactly. Allowed control
characters are tab, carriage return, and line feed. A part has a 256 KiB UTF-8
limit. Read responses calculate SHA-256 over the exact UTF-8 bytes and report
code-point length. A producer's Document content digest is retained as its
claim about the source, not recomputed from an authorized partial projection.

Document detail, search, export, history, and render start with M05's fully
authorized selection and recheck current security before release. The document
record anchors its projection; parts with unreadable current bindings are absent
without placeholders or full-document counts. Historical content uses current
bindings. Markdown is emitted from a small safe subset. Text output uses a
heading title when present, otherwise its text; other part bodies retain their
source characters. Parts are separated by one blank line. Structured parts
always retain the original literal text. Code-like parts are labeled as excerpts unless a
producer explicitly declares one complete unit. No renderer fetches external
content. Ingested prose remains data.

Document history uses backend history entries and their original timestamps,
then reads the corresponding knowledge snapshots to decide whether each part
was attached before or after a change. Applied operation manifests supply
readable candidate IDs and conservative storage-class hints, including expanded
identity operations; they do not replace backend history. A tracked creation
and all subsequent applied records are required to narrow class probes. Legacy
or unknown classes retain the full probe path.
Manifest enumeration is bracketed by workflow-head checks and must match the
authorization plan's workflow head. A concurrent publication therefore requires
a restart before any manifest-derived type hint is used.

One fresh M05 request plan authorizes every candidate before metadata fetches;
the internal history helper cannot publish its results itself. Metadata and
snapshot reads share a bounded eight-request gate and one absolute deadline.
Snapshots are fetched once per revision. A narrow snapshot selection is used
only for tracked document/part IDs without reference-dependent historical
types; otherwise the complete plan preserves presentability rules. Every
failure cancels and awaits sibling reads. Before returning any metadata, the
caller finalizes the original complete plan and verifies the knowledge head
still matches its captured revision. Generic M04 resource history retains its
independent before/after authorization and schema checks.

This optimized document path uses M05's supported-writer coordination boundary:
schema publication is blocked while pending and changes the workflow head.
Privileged out-of-band schema mutations that leave that journal unchanged are
outside this boundary. Runtime startup still verifies the installed registry;
this decision does not claim a distributed transaction or cached authorization.

Plain text preserves source characters and is returned inside an
`application/json` string. It is not HTML. Markdown escapes source markup,
including inside code fences; the exact source bytes remain available in the
structured part or plain-text output. A future browser renderer must apply its
own safe text handling rather than insert these strings as HTML.

Document detail also has an unambiguous `/v1/documents/by-id` route with a
required `document_id` query value. Arbitrary supported document IRIs may end
in an operation suffix. Encoding their slashes cannot distinguish a detail
request from a subroute because ASGI presents a decoded path. The alias uses
the same authenticated, bounded detail service and current-security checks;
it does not change canonical identity or introduce a privileged read path.

Ordinary replacements cannot remove the DocumentPart type. Atomic storage-class
migration or part removal is not an implemented M06 operation; retyping would
bypass structural controls and could leave duplicate canonical records.

Part insertion requires create permission in the part's scope and contribute
permission on the document. A structural move or rank change requires
contribute on each affected document; independent review checks those
document permissions. Default inheritance binds a new part to its document
before the proposal digest is stored. An explicit inherited parent for a part
must be that same document. Evidence tied to a part requires a readable parent
Document and a matching source revision, with selectors checked against the
part's exact text.

Request idempotency hashes the submitted payload before default-binding
resolution. Replaying that request returns its original normalized proposal,
even if the parent policy has changed. New proposals resolve current defaults;
validation and apply still check current bindings and permissions. The proposal
digest includes its resolved scope and inheritance source for exact review.

A cross-document move changes only the knowledge parent. The part retains its
existing scope and security inheritance source, so a later re-scope of its
original security parent still cascades to it. The destination document does
not activate new access. An operator may separately re-scope the part to make
its binding explicit; the current security API does not attach a replacement
inheritance parent. Restoring content likewise leaves current security intact.

## Evidence and limits

The [M05 authorized-selection decision](ADR-0013-authorized-selection.md)
defines the current-binding read boundary reused here. The
[W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/)
defines Text Quote and Text Position selectors. The
[Starlette routing documentation](https://starlette.dev/routing/) requires
specific routes before a general path route; the document subroutes follow
that order. The [OpenFGA Read API documentation](https://github.com/openfga/python-sdk/blob/main/docs/OpenFgaApi.md)
requires an object for a supplied tuple filter; the atomicity test reads all
stored tuples by omitting that filter, then compares binding tuples locally.
M06's real-service tests and report provide the application proof.
The [ASGI HTTP scope specification](https://asgi.readthedocs.io/en/latest/specs/www.html#http-connection-scope)
defines decoded routing paths, and the
[FastAPI query-parameter documentation](https://fastapi.tiangolo.com/tutorial/query-params/)
defines required query values. These explain why the detail alias is needed
in addition to specific-before-general route registration.

Equal ranks can place a newly inserted part before or after another equal-rank
part depending on their stable IRIs. A client needing a specific relative order
must choose an available rank or submit an authorized structural reorder. A
finite key interval may be exhausted. The 2,000-readable-part reconstruction
limit and request deadline return explicit errors rather than partial content
presented as a complete document.
