# M12 secret-scan audit (2026-10-03)

Values were inspected locally; none is copied here.

| File | Detector | Values | Disposition |
|---|---|---|---|
| `tests/browser/vendor/axe-core-4.13.0/PROVENANCE.json` | Base64 High Entropy String | 1 | False positive: the public npm tarball integrity hash (`sha512-…`) of axe-core 4.13.0. Added to `.secrets.baseline` with `is_secret: false`. |
| `tests/unit/m12/test_explorer.py` | Base64 High Entropy String | 2 | False positive: the public PKCE example verifier and challenge from RFC 7636 Appendix B. Marked inline with `pragma: allowlist secret`. |
| `docs/evidence/M12/makako-demo-env-check.txt` | Secret Keyword | 1 | False positive: the line records that a provider-key variable is `unset` (the M09–M11 pattern). Added to `.secrets.baseline` with `is_secret: false` after the demo. |
| `docs/evidence/M12/makako-attempt2-demo-env-check.txt` | Secret Keyword | 1 | The same false positive, in failed demo attempt 2. |
| `docs/evidence/M12/makako-attempt3-demo-env-check.txt` | Secret Keyword | 1 | The same false positive, in failed demo attempt 3. |
