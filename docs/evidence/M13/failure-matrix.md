# M13-T05 failure and race matrix

Each row of MVP_ARCHITECTURE.md §15.4 is mapped to executed checks that use real services:
- the development-stack checks run in the T02 regression gate (`docs/evidence/M13/junit.xml`);
- the `m13/` checks run on the reference deployment (`docs/evidence/M13/reference-junit.xml`).

`scripts/acceptance_matrix.py` fails if any listed check is missing, skipped or failed in those JUnit files. The observed reference-deployment outcomes are in `t05-reference-faults.json`.

| §15.4 failure | Required behavior | Executed checks | Observed outcome |
|---|---|---|---|
| Identity validation cannot be trusted | Deny protected operations | `m03/test_t01_tokens.py` (issuer, audience, purpose, expiry, delegation); `m13/test_t05_failures.py` with Keycloak stopped | Invalid tokens are denied. With Keycloak stopped, C1 is unready and new sign-ins are impossible; already-issued tokens follow the ADR-0008 JWKS cache. |
| Authorization or current-binding service unavailable | Fail closed; no permissive snapshot fallback | `m01/test_t05_freshness.py` (pause and kill); `m03/test_t06_crash.py`; `m09a/test_t03_fail_closed.py`; `m13/test_t05_failures.py` with OpenFGA paused | `/v1/readyz` answers 503. A direct read returns no content: the non-disclosing 404 that M03-T06 verified. |
| Backend timeout with uncertain apply | Reconcile the receipt before retrying | `m04/test_t04_retry_crash.py`; `m13/test_t05_failures.py` (`SIGKILL` of C1 during apply) | After restart, a retry with the same key yields exactly one receipt, and the ChangeSet is `applied`. |
| Invalid or mid-batch failed knowledge operation | No partial visible knowledge transaction | `m01/test_t02_atomic.py`; `m02/test_t03_no_partial.py`; `m13/test_t05_failures.py` with TerminusDB stopped | All or nothing. With the store down, C1 returns 503 and never a partial page. |
| Re-scope interrupted | Block affected reads until safe reconciliation | `m01/test_t06_publication.py`; `m03/test_t06_crash.py`; `m06/test_t04_historical_rescope.py` | Reads of affected resources stay blocked until recovery. |
| New content missing valid current policy | Keep it unavailable | `m01/test_t06_publication.py` (durable deny tombstone); `m13/test_t04_disaster_recovery.py` (restore guard) | Unbound content is unreadable. A restored deployment answers 503 until `dr verify` and `dr release` complete. |
| Draft content changed after approval | Invalidate checks; require revalidation and review | `m04/test_t02_invalidation.py`; `m13/test_t03_knowledge_restore.py` (stale draft after restore) | Mutation invalidates validation and approval. A draft whose base predates a restore cannot apply (409 `stale_base`). |
| Cursor or target state invalidated | Reauthorize and restart explicitly; no silent mixing | `m05/test_t05_cursors.py`; `m07/test_t07_ambiguity_revocation.py`; `m10/test_t03_same_target.py` | Each continuation is reauthorized; a stale cursor is refused. |
| Source acquisition incomplete | Record partial coverage; no false absence | `m08/test_t04_partial.py` | Partial imports are reported as partial. |
| Unsupported schema or interchange | Explicit diagnostic; no silent semantic loss | `m01/test_t07_interchange.py`; `m02` refusals; `m13/test_t06_portability.py` | Remote contexts and incompatible profiles are refused with diagnostics. |

**Plan correction.** M13 D12 expected "protected reads 503" while OpenFGA is paused. The implemented and previously verified behavior (M03-T06) is a non-disclosing 404 with readiness 503. The security requirement is the same in both cases: fail closed, with no permissive fallback and no content. The M13 check asserts that requirement and accepts either status.
