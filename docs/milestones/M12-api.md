# M12 API additions

Three read-only routes. Each requires a bearer token like every other `/v1`
route, accepts no query parameters (any parameter is a 400), and is audited.
The Explorer uses them, and so can any script or agent with the same token.

## `GET /v1/schema`

Installed profile definitions, for building forms.

```json
{
  "instance": "dev",
  "profiles": [
    {
      "name": "core",
      "version": "1.0.0",
      "classes": [
        {
          "iri": "urn:c1:ns:core#Entity",
          "kind": "record",
          "properties": [
            {"iri": "urn:c1:ns:core#lifecycle", "name": "lifecycle",
             "ranges": ["http://www.w3.org/2001/XMLSchema#string"],
             "min_count": 1, "max_count": 1,
             "enum": ["active", "retracted", "superseded"]}
          ]
        }
      ]
    }
  ],
  "available_profiles": ["batteries", "directory", "example-hostile-hints", "..."]
}
```

It describes schema only: no instance data, counts or examples.
`available_profiles` lists the bundled catalog that `install_profile` accepts.
Profile versions were already public through `GET /v1/catalog`.

## `GET /v1/access-scopes/mine`

Active scopes where the caller holds at least one of `reader`, `contributor`,
`creator`, `reviewer` or `access_admin`. Each scope lists only the caller's own
roles:

```json
{"access_scopes": [{"id": "sw-docs", "label": "Published software documentation",
                    "kind": "standard", "roles": ["reader"]}]}
```

Nothing about other members is returned. Retired scopes are not listed. The
check is one OpenFGA batch at a stable workflow revision. A revision change
during the listing, or an authorization outage, gives 503.

## `GET /v1/security-operations`

Security operations the caller proposed, plus re-scopes the caller may approve.
A re-scope can be approved by an admin of its destination scope or of any scope
bound to a lineage source (M11 D7). The listing is newest first and bounded to
100 entries, and `truncated` says when older matching operations exist:

```json
{"security_operations": [{"id": "…", "kind": "rescope", "state": "proposed",
                          "actor": "user:…", "target": "urn:…", "from_scope": "drafts-bob",
                          "to_scope": "sw-docs", "approvals": [], "targets": ["urn:…"],
                          "steps": [], "created": "…", "updated": "…"}],
 "truncated": false}
```

Internal operation kinds (ChangeSet apply, recovery, probe revisions) are not
listed. Recovery payloads are never returned.

**Change to `GET /v1/security-operations/{id}`.** Every listed entry passes the
same check as this read. Reading a re-scope is now also allowed to an admin of
any scope whose approval the operation counts, not only its destination. An
authorization outage gives 503.
