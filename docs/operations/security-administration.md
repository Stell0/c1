# Security administration

## Roles

| Level | Roles | Grants |
|---|---|---|
| Instance (`instance:<id>`) | `access_admin`, `schema_admin`, `operator` | Create scopes and grant instance roles; install profiles; run recovery |
| Scope | `reader`, `contributor`, `creator`, `reviewer`, `access_admin` | Read; edit; create records; review ChangeSets; administer the scope |

The first administrator holds `access_admin` and `schema_admin` on the instance after bootstrap. Grant further instance roles with `POST /v1/instance/grants`. Project membership, domain relationships such as `worksFor`, and operational ownership never grant access.

## Scopes and memberships

- Create a scope: `POST /v1/access-scopes` (`kind` `standard` or `drafting`). The creator becomes its `access_admin`.
- Grant or revoke a role: `POST /v1/access-scopes/{scope}/members`, `DELETE /v1/access-scopes/{scope}/members/{member}?role=…`. A revocation applies to the next request; nothing is cached.
- Retire a scope: `DELETE /v1/access-scopes/{scope}` (refused while resources are bound to it).
- The Explorer's Access page offers the same operations for users who hold the roles; the API decides every action.

## Moving a resource to another scope (re-scope)

A re-scope is a separate, audited security operation with independent review:

1. An administrator of the current and destination scopes proposes it: `POST /v1/access-scopes/{destination}/bindings` with `{"resource_id": …}`.
2. Another administrator approves it: `POST /v1/security-operations/{id}/approve`. For a documentation draft with lineage, approvals must cover the destination and every scope bound to a lineage source (M11).
3. An administrator applies it: `POST /v1/security-operations/{id}/apply`. Apply rechecks the bindings and approvals; any change since the proposal gives 409 `stale_security_operation`.

`GET /v1/security-operations` lists the operations you proposed and the re-scopes you may approve. Ordinary imports, edits, restores and project changes never activate grants or bindings.

## Review rules

With `C1_INDEPENDENT_REVIEW=true` (the default) an author cannot approve their own ChangeSet, and the proposer of a security operation cannot approve it. A reviewer needs review authority over every target; full payload visibility also needs read authority.
