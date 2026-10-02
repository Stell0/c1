# M10 secret-scan audit (2026-10-02)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `docs/evidence/M10/makako-demo-env-check.txt` | Secret Keyword | 1 | False positive: the line records that a provider-key variable is `unset`. This is the same pattern as the M09 audit. |

The entry was added to `.secrets.baseline` with `is_secret: false` after the makako gate. The verified manifest `implementation-files.sha256` therefore differs from the audited source only in `.secrets.baseline`; see `implementation-files-audited.sha256`.
