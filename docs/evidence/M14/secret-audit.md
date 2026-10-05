# M14 secret-scan audit (2026-10-05)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M14/attempt1-results-S.json`, `attempt1-results-M.json` | Hex High Entropy String | 50, 51 | False positives: 64-hex SHA-256 fingerprints of canonicalized benchmark observations (`observation_digests`) and of the corpus and gold data. Added to `.secrets.baseline` with `is_secret: false`. |
| `docs/evidence/M14/corpus-manifest-S.json`, `corpus-manifest-M.json` | Hex High Entropy String | 2, 2 | False positives: `records_sha256` and `gold_sha256` of the synthetic corpus. Added to `.secrets.baseline` with `is_secret: false`. |
| `docs/evidence/M14/results-S.json`, `results-M.json` (attempt 2) and `benchmark/baselines/v1-makako.json` | Hex High Entropy String | see `.secrets.baseline` | False positives: the same SHA-256 observation, corpus and gold digests. Added with `is_secret: false`. |
