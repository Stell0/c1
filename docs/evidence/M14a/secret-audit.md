# M14a secret-scan audit (2026-10-06)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M14a/results-S.json`, `results-M.json` | Hex High Entropy String | 50, 51 | False positives. 49 and 50 are 64-hex SHA-256 fingerprints of canonicalized benchmark observations and of the corpus and gold data; one per file is the Git commit ID in `c1_revision`. Added to `.secrets.baseline` with `is_secret: false`. |
| `docs/evidence/M14a/corpus-manifest-S.json`, `corpus-manifest-M.json` | Hex High Entropy String | 2, 2 | False positives: `records_sha256` and `gold_sha256` of the synthetic corpus (byte-identical to the M14 manifests). Added to `.secrets.baseline` with `is_secret: false`. |
