# M02 detector audit

**Date:** 2026-09-27
**Detector:** pinned `detect-secrets` 1.5.0 with default plugins and filters
**Result:** six findings audited as false positives; no scanner settings changed.

An offline scan used the Git-cached and nonignored untracked files present at
the time, with network verification disabled. It examined 170 files and found
six fingerprints absent from the existing baseline. They were limited to the
following cases:

| Location | Finding | Audit |
|---|---|---|
| `docs/evidence/M02/dependencies.json:10`, `:24`, `:38`, `:52` | Hex high entropy | Each digest was recomputed from the corresponding installed distribution license file and matched. The four files are public license texts for pydantic, pydantic-core, annotated-types, and typing-inspection. |
| `tests/unit/m02/test_storage_guard.py:29` | Secret keyword | The match is a generic placeholder used in a storage configuration validation test. |
| `tests/unit/m02/test_storage_guard.py:47` | Basic authentication | The URI is a local test fixture with generic placeholder credentials and a loopback/private address; it cannot target a public host. |

Exactly these six detector fingerprints were added to `.secrets.baseline` with
`is_secret: false`. Existing audited entries were preserved. No image, runtime
credential, or unrelated fixture finding was added. `make secrets` is the
required final validation; it checks the pinned plugin/filter configuration,
the baseline contents, and tracked plus nonignored untracked files offline.
