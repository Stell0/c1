# M14c — External OIDC Provider Support: execution report

**Gate:** NOT_RUN — complete Gate A and Gate B have not passed.
**Status:** IN_PROGRESS; partial development verification only. No released
compatible artifact or downstream production qualification is claimed.

## Authority and revisions

The owner approved [M14c](M14c.md) and implementation on 2026-10-09:
"Approved—update documents and implement". The prerequisite M14b remains
VERIFIED. M15 remains blocked through M14c verification and release.

Starting source: `ebad219926f547926d9e24059f2129d5970022ff`.
Implementation is currently an uncommitted working-tree candidate; immutable
implementation/source/image pins will be recorded before final qualification.
No completed earlier milestone has been reopened.

## Development verification obtained so far

| Check | Command / observation | Result |
|---|---|---|
| Initial local checking pass | `make check`, with locked Python 3.13 environment; 1,047 pytest cases passed, 137 real-service cases skipped; Ruff, strict mypy, secrets, baseline/profile checks, OpenAPI and license inventory passed. Subsequent product changes require a final rerun. | PASS for that development candidate; skipped cases do not establish T14. |
| Real initialization retry | Pinned TerminusDB 12.0.7 and OpenFGA 1.21.0; repeated initialization preserved store/model/database identity. Source-level probe, not a complete crash matrix. | PASS for the observed retry; T03 remains incomplete. |
| Real Hydra/browser/API workflow | `C1_EXTERNAL=1 PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" UV_CACHE_DIR="$PWD/.uv-cache" uv run --locked pytest --assert=plain -q -s tests/integration/m14c/test_external_browser.py`; one combined live case passed in 21.79 s with the initial memory-backed OpenFGA fixture. | PASS for this case only. Persistent-backend rerun and the remaining scenarios are required. |
| Network dependency boundary | Fixture C1 processes deny administrative provider/engine connections via an audit hook; the supervisor alone configures the real Hydra client/login/consent fixture. | Included in the live case, not a production networking feature. |

The live case covers wrong-account enrollment rejection, pending readiness,
explicit approved browser confirmation, ordinary Explorer access, API ID-token
rejection, denied administration, scope grants, independent review, ChangeSet
apply, context retrieval, and next-request revocation. It does not establish
all session/expiry/rotation/fault/recovery scenarios.

### Findings corrected during development

- Reconciliation must request verbose TerminusDB database metadata and compare
  the exact database path/ownership comment.
- OpenFGA emits empty protobuf defaults; exact model comparison now removes only
  semantically empty defaults while retaining relation/condition semantics.
- Applying an opaque-subject ChangeSet initially reconstructed its encoded
  principal as another raw subject. Canonical decoding and safe actor URIs now
  preserve the original identity and legacy provenance.
- A test fixture initially supplied a non-UUID resource ID unsupported by the
  pinned storage profile; the fixture now supplies a normal canonical ID.
- Initial direct pytest invocation lacked the managed tool PATH/cache settings;
  `make check` uses the repository's locked environment correctly.

Raw OAuth tokens are excluded from public evidence. Temporary diagnostic logs
stay private; final evidence will contain sanitized transcripts, exits, JUnit,
expected-case lists and artifact pins. No test failure is a gate pass.

## Provider and dependency matrix

| Component | Pin / characteristics | Qualification |
|---|---|---|
| Python | Locked 3.13 environment; installed interpreter 3.13.14 | Local development checking only. |
| TerminusDB | 12.0.7, committed digest `sha256:385faf298ad77aaf2d4d6df5e84a4cbe3596d01dab2e3b991af905639ae56388` | Real initializer and live workflow used this image. |
| OpenFGA | 1.21.0, committed digest `sha256:2113c664a486b5da8d7a2cdab479e0d4e30639c80fd2c000540f645c1dbc1e55` | Initial memory-backed live workflow passed; PostgreSQL persistence fixture added for recovery qualification. |
| Ory Hydra | 2.3.0, `sha256:b94007e19a1f7f78157e7f4ea340da8a55b5f104a0f1198755c256f38ef32b4b`; Code+S256, confidential Basic client, explicit API audience and signed access-only `ext` purpose/kind claims | One real Chromium/API case passed. Hydra delegates identity UI/consent to the supervisor fixture; C1 does not provision it. Full profile/lifecycle matrix pending. |
| Reference Keycloak | 26.7.4, existing committed digest | M14c reference bootstrap/Explorer/recovery regressions pending. |
| PostgreSQL | Existing committed 17-alpine digest in the external test fixture | Backup/fresh-node restore qualification pending. |

Loopback HTTP is limited to isolated tests; external production issuers require
HTTPS with system or explicitly configured CA trust. `rfc9068-v1` has signed
unit coverage; real-provider qualification is not yet claimed. Provider-wide
logout/global invalidation is not claimed. Rootless Podman cannot clone namespaces
in this workspace; Docker is available for isolated services. Docker Compose
2.39.4 was downloaded from its official release and verified with SHA-256
`7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4`.

## Required acceptance results

| ID | Full-contract result | Remaining qualification |
|---|---|---|
| T01 | NOT_RUN (partial real initialization evidence) | Final pinned provider-independent initialization and boundary evidence. |
| T02 | NOT_RUN (approved/wrong browser identities exercised) | Complete enrollment negative/concurrency/provider-admin matrix. |
| T03 | NOT_RUN | Every durable initialization/enrollment boundary, actual crashes and uncertain responses. |
| T04 | NOT_RUN (repeated initialization exercised) | Final populated-state/configuration/restart preservation matrix. |
| T05 | NOT_RUN (real login/callback/session creation exercised) | Refresh capabilities, session/token expiry and documented logout matrix. |
| T06 | NOT_RUN (signed unit negatives and real ID/API confusion case) | Complete real provider/JWKS/browser negative matrix. |
| T07 | NOT_RUN (token grant negatives exercised) | Complete registered-client authorization/grant rejection checks. |
| T08 | NOT_RUN (real API scope/review/context/revocation workflow exercised) | Final least-privilege browser/API and modification coverage. |
| T09 | NOT_RUN (pending guard/readiness exercised) | Complete setup surface and restart/expiry guard matrix. |
| T10 | NOT_RUN | Multiple instances/namespaces, outages/delays, real TLS/key rotation. |
| T11 | NOT_RUN (real non-Keycloak fixture exercised) | Full Hydra/reference Keycloak matrix and actionable unsupported capabilities. |
| T12 | NOT_RUN | Qualified public maintenance/consistency schemas and exclusive/online operation checks. |
| T13 | NOT_RUN | Complete real backup/fresh-node recovery and failure matrix. |
| T14 | NOT_RUN | Final full reference, relevant M03/M04/M12/M13/M14a/M14b and write regressions without AI credentials. |

## Gate outcomes and next work

**Gate A:** NOT_RUN; partial evidence only. **Gate B:** NOT_RUN. Neither gate
may pass while mandatory cases remain failed or unexecuted. Release/publication
and downstream consumption remain pending.

Continue W1–W5 qualification, persistent-backend recovery and reference regressions;
complete review and sanitized reproducible evidence; publish/pin only the verified
compatible artifact. Do not begin M15.
