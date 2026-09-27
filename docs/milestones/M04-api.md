# M04 API notes

This is the request contract for the M04 implementation under verification.
Every route below requires a bearer token from the configured issuer. The
server chooses the repository, issuer, principal, and authorization store from
trusted startup settings; request selectors for these are rejected. Request
bodies are limited to 1 MiB and reject unknown fields. Failures use content-free
Problem Details. The browser and external clients use the same routes.

`GET /v1/instance` returns `instance_id`, `instance_base`, and the opaque
`knowledge_revision` to use as a ChangeSet's `base_revision`. It returns `503`
while the repository is unready, including during unpublished operations.

## ChangeSet workflow

| Route | Request | Result |
|---|---|---|
| `POST /v1/changesets` | `Idempotency-Key` header and a ChangeSet body | Creates a draft (`201`); replay of the same key and body returns the stored result with `replayed: true` (`200`). |
| `GET /v1/changesets` | No query parameters | Lists the caller's visible drafts and reviews. |
| `GET /v1/changesets/{id}` | No query parameters | Returns a visible ChangeSet. |
| `PUT /v1/changesets/{id}/operations` | `{"operations": [...]}` | Replaces the operations and returns to `draft`; prior validation and approval no longer apply. |
| `POST /v1/changesets/{id}/submit` | Empty body or `{}` | Submits and runs validation. |
| `POST /v1/changesets/{id}/validate` | Empty body or `{}` | Validates a submitted ChangeSet on demand. |
| `GET /v1/changesets/{id}/validation` | No query parameters | Returns the visible report with diagnostics and permission preview. |
| `POST /v1/changesets/{id}/approve` | Empty body or `{}` | Records a reviewer decision on the exact validated payload. |
| `POST /v1/changesets/{id}/reject` | `{"reason": "..."}` | Records a reviewer rejection. |
| `POST /v1/changesets/{id}/apply` | `Idempotency-Key` header; empty body or `{}` | Rechecks the approved payload, head, current bindings, and every permission before committing. |
| `POST /v1/changesets/{id}/withdraw` | Empty body or `{}` | Withdraws an unapplied ChangeSet. |
| `POST /v1/changesets/{id}/rebase` | `{"base_revision": "branch:..."}` | Starts a new attempt at that knowledge revision; validation and review are required again. |

The `Idempotency-Key` value must be 1–128 printable ASCII characters. Reusing
one key with a different request digest returns `422`. The service binds keys
to the authenticated principal and repository. A ChangeSet can have at most
200 operations. Its creation body has `base_revision`, `operations`, optional
`rationale`, and optional `restores_from_revision` for a compensating restore.
Read the current `base_revision` from `GET /v1/instance`; a concurrent commit
can make it stale before apply, in which case the author must rebase and obtain
new validation and review.

The operation forms are:

```json
{"kind":"create","record":{"id":"urn:c1:instance:dev:entity/example","types":["urn:c1:ns:core#Entity"],"properties":{}},"scope_id":"urn:c1:instance:dev:scope/example"}
{"kind":"replace","resource_id":"urn:c1:instance:dev:entity/example","record":{"id":"urn:c1:instance:dev:entity/example","types":["urn:c1:ns:core#Entity"],"properties":{}},"reason":"Correction"}
{"kind":"install_profile","profile":"example-vehicle"}
```

`create` may omit `record.id` to have the server mint it. It may also declare
`inherited_from`. Content and `install_profile` operations cannot be mixed in
one ChangeSet. Records above illustrate the shape only; real records must pass
the installed profile's validation and all reference checks. An assertion
without evidence must be an attributed manual statement. The server preserves
conflicting claims with their provenance.

The author can inspect the draft and report. A reviewer needs review authority
over every target; full payload visibility also requires read authority over
targets and references. Other callers receive the same `404` as for an unknown
ChangeSet. With independent review enabled, the author cannot approve their
own ChangeSet. A scope move remains a separate audited security operation.

## Reading content and history

| Route | Query | Result |
|---|---|---|
| `GET /v1/resources/{id}` | Optional `revision=branch:...` | Returns the canonical record at head or the selected knowledge commit. |
| `GET /v1/history` | Required `resource_id`; optional `limit` (1–100, default 20) and `cursor` | Returns newest-first revision entries and an optional `next_cursor`. |

Both routes authorize the stable resource ID against **current** grants and
bindings, including for an old revision. Hidden and nonexistent resources have
identical `404` responses. Each history page rechecks authorization; the cursor
holds a knowledge revision and offset, not a permission grant. A malformed
cursor returns `400`; a cursor from an older head returns `409`. History
entries contain the commit revision, recorded time, ChangeSet ID, and attempt
when the commit has a ChangeSet receipt. The API does not return arbitrary
backend queries or expose content through scope membership alone.

## Development demonstration

From the repository root, run `make stack-up`, then
`uv run --locked python -m scripts.demo_m04`, then `make stack-down`. The script
uses isolated test databases and a fresh OpenFGA store, builds synthetic source,
evidence, imported and manual assertions, and submits them as one ChangeSet.
It checks that an independent reviewer applies exactly one new knowledge
commit. Its JSON output contains the receipt from that commit message and the
authorized history listing for the imported assertion; no token or record body
is printed. The isolated resources are removed when the script exits.
