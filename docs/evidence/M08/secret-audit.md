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

## Post-gate evidence (audited 2026-09-29, recorded during M09)

The M08 demonstration evidence was written after the M08 `make check`, so its
secret scan first ran in the M09 check. Values were inspected locally.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M08/demo-env-check.txt`, `attempt1-demo-env-check.txt` | Secret Keyword | 1 each | False positive: the line records that the provider-key variable is `unset`. |
| `docs/evidence/M08/demo.log` | Hex High Entropy String | 2 | False positive: the public, deterministic fixture git commit IDs of a1 and b1. |
