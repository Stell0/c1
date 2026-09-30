# M09 secret-scan audit (2026-09-30)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M09/makako-demo-env-check.txt` | Secret Keyword | 1 | False positive: the line records that a provider-key variable is `unset`. |

The entry was added to `.secrets.baseline` with `is_secret: false`. This happened after the makako gate, so the verified manifest `implementation-files.sha256` differs from the audited source only in `.secrets.baseline`; see `implementation-files-audited.sha256`.
