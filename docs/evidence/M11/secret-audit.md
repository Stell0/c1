# M11 secret-scan audit (2026-10-03)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M11/makako-demo-env-check.txt` | Secret Keyword | 1 | False positive: the line records that a provider-key variable is `unset` (the M09 and M10 pattern). |
| `docs/evidence/M11/makako-attempt1-demo-env-check.txt` | Secret Keyword | 1 | The same false positive, in the failed first demo attempt. |

Both entries were added to `.secrets.baseline` with `is_secret: false` after the makako gate.
