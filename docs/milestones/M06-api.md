# M06 document API

All routes require an API access token. They use current resource bindings even
when `revision` selects an older knowledge commit. A document is the anchor:
unreadable and nonexistent documents both return 404. Reading the document does
not grant access to its parts.

| Route | Parameters | Result |
|---|---|---|
| `GET /v1/documents` | `title`, `text_contains`, `kind`, `revision`, `limit`, `cursor` | Authorized documents, readable matching part IDs, match explanations, count and continuation |
| `GET /v1/documents/{id}` | `revision` | Document record and compact ordered readable parts |
| `GET /v1/documents/by-id` | Required `document_id`, optional `revision` | The same compact detail projection, for any supported canonical IRI |
| `GET /v1/documents/{id}/parts` | `text_contains`, `revision`, `limit`, `cursor` | Ordered readable parts with count and continuation |
| `GET /v1/documents/{id}/render` | `format=markdown\|text`, `revision` | Deterministic content string |
| `GET /v1/documents/{id}/export` | `format=jsonld\|text`, `revision` | Authorized JSON-LD snapshot or plain text |
| `GET /v1/documents/{id}/history` | `limit`, `cursor` | Revisions changing the document or its currently readable parts |

For detail, use `/v1/documents/by-id` with the canonical ID as an encoded query
value. This avoids ambiguity for IDs ending in `/parts`, `/render`, `/export`,
or `/history`: servers decode encoded slashes before path routing. The existing
detail path remains available for other IDs. Operation routes append their
suffix to the URL-encoded complete canonical ID.

Document and part pages allow
1–200 items (default 50); history allows 1–100 (default 20). Reconstruction
allows at most 2000 readable parts and uses the configured query time budget.
Limit exhaustion is an explicit error. Signed cursors pin a revision and are
reauthorized at every continuation. Document history requires a restart if the
head changes between pages (`409`, `C1-DC-014`). History assembly bounds
readable candidate parts, each resource's entries, and the combined revisions
at 2000; exhaustion returns `C1-DC-006` before publishing a partial history.

`title` matches a normalized substring of the document title. `text_contains`
matches a normalized substring of readable part text or titles, or the document
title. Normalization is NFKC followed by casefold; the stored and returned text
is unchanged. Hidden text cannot cause a match. No snippets, stemming,
translations, or inferred synonyms are produced.

Each part payload contains `part_id`, `title`, `kind`, `order_key`, `text`,
`text_digest`, and `text_length`. The digest covers the exact UTF-8 text bytes;
length counts Unicode code points. Parts sort by `(order_key, canonical ID)`.
Equal rank strings are valid, so validation cannot reveal a protected sibling's
rank. Responses do not report omitted parts, their positions, or document
completeness.

Text rendering joins parts with one blank line. Headings use their title when
available, otherwise their text; other parts use their exact text body. The
structured part payload always retains the original literal text, including
when a heading title supplies its display label.

Writes use the existing ChangeSet API. A new part requires creation permission
in its scope and contribution permission on its parent document. Reordering
requires contribution permission on the document; a cross-document move
requires it on both documents. Review checks document review permission as
well. A part without an explicit scope defaults to inheriting its document's
current binding. An explicit inheritance parent must be that document.

Ordinary replacements cannot remove the `DocumentPart` type. Storage-class
migration is not a document edit operation.

A cross-document move preserves the part's existing scope and inheritance
source. Re-scoping the original security parent therefore still affects that
part; the new knowledge parent grants no access. A separate authorized re-scope
can detach the part's inheritance and make its binding explicit. Content
restores also preserve the current binding.

Text allows tabs and CR/LF but rejects other control characters and bodies over
256 KiB. Parts are flat; nesting predicates are rejected. Evidence selectors
on a part are checked against its exact text and readable parent document's
source revision. Native documents use the ChangeSet base revision when no
source revision is declared. Selector offsets count code points.

Markdown is a safe emitted subset: HTML, links, images and reference definitions
are neutralized; code uses fences longer than any contained backtick run.
`code` parts are labeled `excerpt`; `code-unit` parts are labeled `complete
unit` according to the producer's declaration. Plain text preserves each part
and joins parts with one blank line. Neither format executes source commands
or fetches external content.
