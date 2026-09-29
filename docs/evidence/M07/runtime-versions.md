# M07 runtime and pinned image versions

This note distinguishes versions observed in retained command output from
versions declared by the repository. Running image identity was checked
read-only against the repository pins; no service API was called to query
software-version endpoints.

## Observed test/runtime evidence

| Component | Evidence | Version or result |
|---|---|---|
| Completed local-check interpreter | `check-final-gate.log` test-session header; `bootstrap.log` records Python 3.13 installed/available | Python 3.13.14; the project requires Python `>=3.13,<3.14`. |
| Completed local-check pytest | `check-final-gate.log` test-session header | pytest 9.0.2; pluggy 1.6.0. |
| Local services at bootstrap | `stack-up.log` | TerminusDB, OpenFGA, Keycloak, identity, authorization, and databases reported ready. The log does not report their running image versions. |
| Inputs checked after the corrected M07 suite | `manifest-check-after-m07.log`, `implementation-files-corrected-m07.sha256`, and `verify-manifest.py` | PASS at that earlier check: all 339 historical M07 inputs unchanged; symlinks are hashed as their link text. This snapshot predates the history and CAS fixes and is not the current audited 350-input D21 source. |
| History-follow-up input snapshot | `implementation-files-history-probe.sha256` | 342 inputs captured for the cohort timing probe, which failed at T04. This is not a final source freeze. |
| Historical history-fix local check | `check-history-fix-corrected.log` | Exit 0 at that earlier source: Python 3.13.14 / pytest 9.0.2; 646 passed, 79 skipped, 17 warnings; mypy 240 source files; Ruff, secret scan (647 files), baseline, and profile checks passed. The preceding `check-history-fix.log` failed at Ruff import formatting and remains preserved. This is not the latest check or current source. |
| History-prefetch local check | `check-history-prefetch-final.log` | Exit 0; Python 3.13.14 / pytest 9.0.2; 659 passed, 79 skipped, 17 warnings; mypy 241 source files; Ruff, secret scan (664 files), baseline, and profile checks passed. Its unchanged T04 timing rerun failed at line 174; the guarded timing-only diagnostic later passed one T04 run. |
| History-prefetch timing input snapshot | `implementation-files-prefetch-probe.sha256` | 343 inputs captured for the timing rerun; not the final M07 implementation revision. |
| History-prefetch wheel | `wheel-prefetch-build.log`, `wheel-prefetch-check.md` | Build and inspection passed; 117 entries; SHA-256 `041d1e060768ac685babeeae857dbdfc1f19fa60f915d2e1dccee42b19794741`. Packaging evidence only. |
| Guarded full local check | `check-guarded-final-permitted.log` | Exit 0; Python 3.13.14 / pytest 9.0.2; 689 passed, 79 skipped, 17 warnings; mypy 242 source files; Ruff, secret scan (676 files), baseline, and profile checks passed. Earlier format and sandbox socket failures are retained in the preceding check logs. |
| Guarded timing input snapshot and wheel | `implementation-files-guarded-probe.sha256`, `wheel-guarded-check.md` | 344 inputs captured for the guarded timing run; wheel inspection passed with 117 entries and SHA-256 `cdcf2ae8eb668769bc429c539892c161502e239b9ce1b0d60ea5937677c4c5e4`. The 344-input manifest was verified immediately before the final live gate. |
| Guarded timing plugin | `timing-plugin-guarded-review.txt` | `AuthorizedSelection.finalize_after` timing hook; SHA-256 `3753e9408c8799a8b0bd4d1a2a9a048d60c7a24568210a94320942022b386148`. Static Ruff, format, and strict mypy checks passed; no pytest/API/live-service call was run by this plugin check. |
| Guarded T04 timing-only diagnostic | `m06-t04-timing-guarded-exit.txt`, `.json`, `.log`, and `-junit.xml` | Exit 0; one unchanged T04 test passed in 751.79 s. Request 13 returned HTTP 200 in 1,997.916 ms. Diagnostic only; it does not replace the failed final combined live gate. |
| Final live regression gate | `manifest-check-before-final-live.log`, `final-live-integration.log`, `final-live-junit.xml`, `final-live-exit.txt`, `run-final-live-gate.sh` | All 344 run inputs verified before launch. Exit 1 after 2,749.06 s: M06-T04 passed, then M07-T01 failed with `C1-QY-053`; `-x` stopped before later tests. |
| Cold entity lookup diagnostics | `entity-phase-first.json`, `entity-phase-fga32.json`, `entity-phase-provisional-index.json`, and review notes | Initial production-setting cold/warm pair returned 503 at 2,002.195 ms and 200 at 1,396.833 ms. FGA-32 experiment did not establish benefit. After scoped CAS repair, the read-only cold/warm pair returned 200 at 1,813.570/1,351.835 ms (production concurrency 16). The 397.102 to 214.143 ms cold-index phase change is an observed comparison, not causal proof because other phases varied. |
| Provisional cold-index local check and review | `check-provisional-index.log`, `check-provisional-index-corrected.log`, `check-provisional-index-cas.log`, and `implementation-files-provisional-index.sha256` | Initial check failed only Ruff formatting; intermediate check passed 715 tests but predates the cache-race repair. CAS-repair check exited 0: 727 passed, 79 skipped, 17 warnings; Ruff 347, mypy 243, secrets 707, baseline/profile passed. Astra re-reviewed 12 race cases without a remaining blocker; advisor did not run tests or services. The 345-input implementation snapshot was verified before the corrected live run, which terminated at M05-T01; prior 344-input manifest is historical. |
| Provisional cold-index diagnostic | `entity-phase-provisional-index.json`, `.log`, and `-exit.txt` | Read-only cold/warm entity queries returned HTTP 200 in 1,813.570/1,351.835 ms at production FGA concurrency 16 and gate eight. Each completed 225 FGA calls; peak 16, no active/cancelled remainder. Cold index read was 214.143 ms. Diagnostic only, not a stable latency or live-gate result. |
| Corrected post-CAS live gate | `manifest-check-before-corrected-live.log`, `run-corrected-live-gate.sh`, `corrected-live-integration.log`, `corrected-live-junit.xml`, and `corrected-live-exit.txt` | All 345 inputs were verified before launch; the 117-entry wheel SHA-256 is `1777fe25920584396d593020e7bb6bc94bc2660eb793d7207b157533cff1d4f3`. Terminal FAIL: 68 passed, one failed, 14 warnings in 13,675.26 s; JUnit records 69 cases with zero skips/errors. M05-T01 failed with `httpx.RemoteProtocolError: Server disconnected without sending a response`; prior M07, M06, and M01–M04 cases passed, as did M05 backend-fetch. Pytest 1, tee 0, restoration 0, wrapper 1; 10 later selected tests were not run. This is an undiagnosed transport failure, not a `time_budget` failure. |
| Focused M05 transport diagnostic | `transport-diagnostic-m05.log`, `transport-diagnostic-m05-junit.xml`, `transport-diagnostic-m05-case-check.json`, `transport-diagnostic-m05-exit.txt`, and `manifest-check-after-transport-diagnostic.log` | Exit 0; 12/12 unique expected M05 cases passed in 2,011.05 s, one warning; no failures/skips and no failure frames. The 345-input implementation manifest remained unchanged. This does not explain the original disconnect. |
| Controlled stack recovery | `recovery-stack-down.log`, `recovery-stack-up.log`, their exit files, `post-transport-recovery-service-state.json`, and `running-images-recovery-corrected.log` | Stack-down/up, tee, and wrappers exited 0; existing volumes/configuration retained. Bounded state check reported one running, non-OOM-killed container per service. The first image-check command failed because `PYTHONPATH` was missing; the corrected read-only check matched all four configured image pins. |
| Post-recovery full live gate | `manifest-check-before-post-transport-live.log`, `run-post-transport-live-gate.sh`, `post-transport-live-integration.log`, `post-transport-live-junit.xml`, `post-transport-live-exit.txt` | Started after the verified, unchanged 345-input snapshot. Terminal FAIL at first M06-T04 test line 216: expected 200, got 503 `C1-DC-012` (`time_budget`), one failed in 840.02 s, 78 selected tests not run; pytest 1, tee 0, restoration 0, wrapper 1. M05 was not reached. |
| Corrected M07 integration run | `m07-corrected-exit.txt`, `m07-corrected-junit.xml` | Exit 0; seven M07 cases passed, no failures, errors, or skips on that earlier snapshot. Later M01–M06 regression and combined runs are recorded separately. |
| Current audited D21 source and local check | `implementation-files-read-retry-audited.sha256`, `check-read-retry-audited.log`, `check-read-retry-audited-exit.txt`, and `read-retry-secret-audit.md` | 350 inputs, SHA-256 `f00adf1914baa83cf2903f60481a6af55dfe34a384a2391593b95dce00fa491f`. The corrected `make check` observed Python 3.13.14 / pytest 9.0.2 and exited 0: 810 passed, 79 skipped, 17 warnings; Ruff 371, mypy 248, secrets 829, baseline/profile passed. Compared with the preserved pre-audit manifest, the only source-input change is `.secrets.baseline` for one audited false-positive finding; detector filters are unchanged. |
| Current running pinned images | `running-images-read-retry.log` and `running-image-check.py` | Read-only verification after the D21 source audit matched all four configured service image config digests and repository digests. These are the same image pins recorded below; this does not assert service behavior or gate completion. |
| D21 wheel | `wheel-read-retry-build.log` and `wheel-read-retry-check.md` | Build and inspection passed; 117 entries; SHA-256 `e209ce6709e0249252c7e1c08cc651bc8482f81cb526f36e3b5f8c96ed3e2309`. Built before the baseline-only audit change; packaged runtime files match the audited source, and no dotenv, uv cache, or evidence paths are included. |
| D21 focused and complete live gates | `read-retry-focused-integration.log`, `read-retry-focused-junit.xml`, `read-retry-focused-case-check.json`, `read-retry-live-integration.log`, `manifest-check-before-read-retry-live.log` | Focused six-case M04 run passed in 504.33 s with all exits 0, exact unique JUnit cases, and unchanged audited manifest. The complete 79-case gate began at approximately 2026-09-29 01:57 UTC; nine cases have passed so far. It remains active without terminal JUnit or exit evidence. |

The pinned Python application and development-tool requirements are in
`pyproject.toml` and `uv.lock`. Selected declared versions are:

| Package | Declared/locked version |
|---|---:|
| FastAPI / Starlette / Uvicorn | 0.141.1 / 1.7.0 / 0.54.0 |
| Pydantic / HTTPX | 2.13.5 / 0.28.1 |
| RDFLib / PySHACL | 7.6.0 / 0.40.1 |
| PyJWT / cryptography | 2.15.0 / 50.0.1 |
| pytest / mypy / Ruff | 9.0.2 / 2.3.1 / 0.16.9 |
| OpenFGA SDK | 0.10.4 |

These are repository-pinned package versions; Python 3.13.14 and pytest 9.0.2
were visible in the completed local-check output. No separate runtime-version
banner is retained for the M07 integration process, so this note does not
assert process-specific package versions from that run.

## Deployment image declarations

`deployment/images.json` records the human-readable tag, image-index digest,
platform digest, and config digest; `deployment/compose.yaml` references image
digests. The corrected read-only verifier confirmed that each of the four
running C1 services had the exact declared image config digest and at least
one exact repository digest matching either the pinned image or its platform
digest. It did not read container environments or query service APIs.

| Service | Configured image tag | Verified running image config digest | Verified repository digest(s) | Platform |
|---|---|---|---|---|
| TerminusDB | `v12.0.7` | `sha256:3308827f2e9e76d259fdd1fa04d546330b24d3b912363172f6ced84a4e2b8243` | `sha256:385faf298ad77aaf2d4d6df5e84a4cbe3596d01dab2e3b991af905639ae56388`; `sha256:c5c70435f944a0e91b6846fa6a70c8b6956cb36e5712e60789cd7a45a7084f73` | `linux/amd64` |
| OpenFGA | `v1.21.0` | `sha256:e7bc1233d821701d8f39b1c837fc1c09eb863637ce81b0cf7db3368d72c0d69b` | `sha256:2113c664a486b5da8d7a2cdab479e0d4e30639c80fd2c000540f645c1dbc1e55`; `sha256:51bece5c31783bfeb150eae0f1c818ae804c50d39e0a311c43ff5357fed6debd` | `linux/amd64` |
| Keycloak | `26.7.4` | `sha256:b2f3e1b85071d17a1da8d2cbcc54707853d19c74ae027071789ea1bb12b3ec89` | `sha256:82a77884f3af238beab1e7afd63b5f530e1b5c0590bd7aa60b40a40463e29b2c`; `sha256:3d911baa186f352563854039b95f21a7e2c01c76b527fdc64f24a0885b927bdf` | `linux/amd64` |
| PostgreSQL | `17-alpine` | `sha256:79bd7c99e923138f136f8009d6bffa66e21e9d4fda5c0c561b00fc9c90cfe537` | `sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24`; `sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3` | `linux/amd64` |

The metadata file also records upstream source/license provenance. For
PostgreSQL, its source reference is `REL_17_11`; the configured image tag
remains `17-alpine`.

The first [running-image check](running-images.log) exited 1 because Podman
reported a bare 64-character image config ID while the manifest used the
`sha256:` prefix. The corrected helper accepts that optional prefix only for a
strict 64-character lowercase hexadecimal digest, and the corrected check
passed for all four services. Manifest pins were not changed. Both attempts
are retained.

## Reproduction sources

- [Bootstrap log](bootstrap.log)
- [Stack startup log](stack-up.log)
- [Final local check log](check-final-gate.log)
- [Deployment image metadata](../../../deployment/images.json)
- [Digest-pinned compose file](../../../deployment/compose.yaml)
- [Frozen-input verification during the earlier M07 gate](manifest-check-during-gate.log)
- [339-input verification after corrected M07](manifest-check-after-m07.log)
- [First running-image check failure](running-images.log)
- [Corrected running-image verification](running-images-corrected.log) and [read-only helper](running-image-check.py)
