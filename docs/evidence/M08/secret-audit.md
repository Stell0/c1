# M08 secret-scan audit (2026-09-29)

The first M08 `make check` failed only its secret scan. Every flagged value
was inspected locally; no raw values are copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `fixtures/software-integration/fixture.json` | Hex High Entropy String | 8 | False positive: the synthetic repositories' git commit and tree IDs, which are deterministic and public by construction. |
| `fixtures/software-integration/scip/PROVENANCE.json` | Hex High Entropy String | 10 | False positive: SHA-256 digests of checked-in fixture trees, generated indexes, the npm lockfile, and the published scip release archive. |
| `fixtures/software-integration/tools/generate_scip.sh` | Hex High Entropy String | 1 | False positive: the published SHA-256 of the scip v0.10.0 release archive. |

These entries were added to `.secrets.baseline` with `is_secret: false`.
Detector plugins and filters are unchanged.
