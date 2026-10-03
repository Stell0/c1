# Import and export

## Snapshot export is not a backup

`GET /v1/export` returns an **authorized snapshot**: the records the caller may read at one knowledge revision, as JSON-LD with C1's bundled context identifier, in signed pages. It contains no history, no other user's view, no access policy, no OpenFGA tuples and no workflow records. Use it to exchange data. Use `c1-admin backup` (see [backup-restore.md](backup-restore.md)) to preserve the repository.

## JSON-LD profile

The supported interchange profile is RDF 1.1 / JSON-LD 1.1 with the bundled contexts only:

- The `@context` must be a bundled context identifier. Remote contexts are refused with an explicit diagnostic and never fetched.
- Assertion identities, typed and language-tagged literals, qualifiers and provenance round-trip unchanged (M02, and M13-T06 on the reference deployment, which also parses the export with rdflib).
- Unsupported constructs (for example `@reverse`, `@nest`, blank-node assertions) are refused; nothing is persisted from a refused document.

## Importing data

There is no bulk-import bypass. Producers convert their data into records and submit them through ordinary ChangeSets, which validate every record against the installed profiles (`c1.interchange.import_jsonld` performs the same normalization for JSON-LD input). Imported fields never activate grants or bindings; new records are bound to the scope chosen in the ChangeSet operation.
