# Current bindings and recovery

## Current bindings govern old content

Every resource has one current binding to a scope, kept in the C1 journal and mirrored as an OpenFGA `bound_to` tuple. Every read, including a read of an old knowledge revision, is authorized against the **current** binding and current grants. An `access_scope` value stored in an old revision is history, not authority. When a resource exists only in history, its binding remains as a deny tombstone.

## Interrupted security operations

Security operations are journaled before OpenFGA is changed. While an operation is pending, the affected resources are denied and `/v1/readyz` reports unready. At startup C1 reconciles pending operations; an operator can also run `POST /v1/security-operations/recover` (instance `operator`). A missing, stale or unresolved binding always fails closed.

## Consistency check

```sh
uv run --locked c1-admin consistency
```

compares every active journal binding with the live OpenFGA `bound_to` tuples and counts pending operations and grant tuples. It exits non-zero on any difference. Run it after maintenance, before releasing a restored deployment, and whenever OpenFGA was changed outside C1. Do not edit OpenFGA tuples by hand; repair through C1's operations or re-provisioning.

## Fault behavior

| Fault | Behavior |
|---|---|
| OpenFGA unavailable | Readiness 503; protected requests 503; no permissive fallback |
| Identity provider unavailable | Readiness 503; already-issued tokens validate with cached keys until they expire; no new sign-ins |
| TerminusDB unavailable | Requests needing knowledge or the journal fail with 503; no partial page |
| C1 killed during apply | After restart, the ChangeSet is reconciled to exactly one applied outcome; a retry with the same idempotency key replays it |
| Restored deployment not yet verified | Every request 503 until `c1-admin dr release` (see [backup-restore.md](backup-restore.md)) |

These behaviors are exercised by M13-T05 on the reference deployment and by the M01–M12 fault tests.
