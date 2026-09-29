# Final secret-scan audit (2026-09-29)

After the final-source gate, `make check` failed only its secret scan. Two new
evidence files were flagged. Both were inspected locally; no raw values are
copied here.

| File | Detector | Line | Disposition |
|---|---|---|---|
| `docs/evidence/M07/final-context-demo-env-check.txt` | Secret Keyword | 1 | False positive: the line records a provider-key variable name with the literal value `unset`. |
| `docs/evidence/M07/run-fixture-cli-gate-deadline.py` | Base64 High Entropy String | 176 | False positive: a status string identical to line 176 of `run-fixture-cli-gate.py`, which the baseline already records as not a secret. |

Both entries were added to `.secrets.baseline` with `is_secret: false`.
Detector plugins and filters are unchanged. The corrected `make check` passed
(810 passed, 79 skipped, 17 warnings; secret check 965 files); see
[log](check-final-audited.log).

The audited manifest
[`implementation-files-final-audited.sha256`](implementation-files-final-audited.sha256)
differs from the gate manifest `implementation-files-budget-harness.sha256`
only in `.secrets.baseline`. No product runtime path reads that file; only the local secret check and the unit test `tests/test_secret_hygiene.py` read it, and both passed in the corrected `make check`. The same
precedent was used for the D21 audited manifest.
