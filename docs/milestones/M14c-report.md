# M14c — External OIDC Provider Support: execution report

**Gate:** VERIFIED. Gate A PASS; Gate B PASS. T01–T14 and release requirements pass.
**Status:** VERIFIED. The compatible upstream artifact is published and pinned; downstream deployments still require qualification of their own configuration and lifecycle.

## Authority and immutable revisions

The owner approved [M14c](M14c.md) and implementation on 2026-10-09:
“Approved—update documents and implement”. M14b remains VERIFIED; completed
milestones were not reopened. No M15–M18 implementation was undertaken.

Approved plan is recorded in `78def435a9e020c56d2596f5e4e7d48d990463c7`.
Starting revision: `ebad219926f547926d9e24059f2129d5970022ff`.
Application candidate: `3789ce467c37cae70fe66e5c796f7777d715ca74`.
The subsequent fixture-only endpoint correction is recorded in
[tested-environment.json](../evidence/M14c/tested-environment.json).
Tested amd64 image: `localhost/c1:0.1.0rc2`,
`sha256:75dd59a5d14e9182fec5665578e31e3f4f7e3873b1348b9a944be975e0005873`.
The image OCI revision identifies the application candidate. Released source/tag: `d6d9f8614c8dfd52591ec1d2402438f7b6a626f7`,
[`v0.1.0rc2`](https://github.com/Stell0/c1/releases/tag/v0.1.0rc2) (published pre-release).
Imported release image: `sha256:b1546cbbf032eedf7c3c58cb1b4e371d9aab62aa054a1515aa092ef7a3b0b653`.
[Artifact pins](../evidence/M14c/artifact-pins.json), [checksums](../evidence/M14c/SHA256SUMS)
and [publication verification](../evidence/M14c/published-release.json) identify
the wheel, source archive and complete amd64 Docker archive. All seven uploaded
asset digests/sizes match local files; downloaded checksum/pin files match.
The tag/source archive records the candidate before publication; this report
closes publication on main afterward. No tag or artifact was moved/replaced.

## Delivered contracts and behavior

[ADR-0027](../decisions/ADR-0027-external-oidc.md) records the choices.
[Installation](../operations/external-oidc.md),
[schemas](../operations/external-oidc-contract-v1.json), and
[recovery](../operations/external-oidc-recovery.md) document public interfaces.

- Version-1 `C1_*` configuration and public `c1-admin application` JSON operations
  replace dependence on reference Compose or IdP administration.
- Initialization persists intent before backend resources, reconciles uncertain
  responses, and preserves owned store/model/database and namespace identifiers.
  Reference bootstrap provisions its own Keycloak, then uses the same initializer.
- Exact operator-approved issuer/subject, protected expiry/cancellation, authenticated
  confirmation, and durable guards prevent first-login administration. Only
  `access_admin` and `schema_admin` are granted; live consistency precedes readiness.
- Exact endpoint trust, TLS, signed access-purpose profiles, ID/access separation,
  reversible opaque subjects, and optional refresh/logout support external providers
  while retaining legacy principal identifiers and service behavior.
- Version-2 application-only backups, guarded fresh-node restore, independent
  namespace attestation plus normal user-token proof, explicit snapshot acceptance,
  fresh consistency and bounded release retain fail-closed recovery.

## Reproducible environment and commands

Exact pins, lock checksum and runtime versions are in
[tested-environment.json](../evidence/M14c/tested-environment.json).
Host Python is 3.13.14; image Python is 3.13.16. Docker 29.1.3 and Compose
2.39.4 execute committed amd64 image digests. The downloaded official Compose
binary SHA-256 is `7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4`.
Locked Playwright 1.63.0 supplies real Chromium.

| Service | Version / profile |
|---|---|
| TerminusDB | 12.0.7; real knowledge/workflow storage and cold-storage backup. |
| OpenFGA | 1.21.0; PostgreSQL persistence, real checks/grants/revocations. |
| PostgreSQL | 17.11 (pinned 17-alpine); custom-format application authorization dump. |
| Keycloak | 26.7.4; reference `c1-v1`, confidential Code+S256 client. |
| Ory Hydra | 2.3.0; `hydra-jwt-v1`, confidential Basic Code+S256, explicit API audience and access-only signed `ext` claims. |

Hydra is independently managed by the supervisor fixture. Its synthetic delegated
login/consent UI supplies identities; the real provider performs discovery,
PKCE, signatures, access/ID issuance, refresh, logout and key rotation. C1 cannot
contact its administration port or container-engine sockets. No provider database,
signing key or administrator credential is a C1 external backup requirement.
The tagged Hydra [license](../evidence/M14c/licenses/hydra-LICENSE) was inspected.

Fixtures use projects `c1-dev`, `c1-m14c-external`, `c1-m14c-reference`, and an
isolated fresh recovery target. Original occupied development ports/configuration
are untouched. See [reproduction instructions](../evidence/M14c/README.md).
The reference harness always starts fresh; it does not reuse an existing deployment.

```sh
make bootstrap
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" uv run --locked playwright install chromium
docker build -f deployment/reference/Containerfile \
  --build-arg C1_REVISION="$(git rev-parse HEAD)" -t localhost/c1:0.1.0rc2 .
bash docs/evidence/M14c/run-gate.sh check
bash docs/evidence/M14c/run-gate.sh external
bash docs/evidence/M14c/run-gate.sh regression
bash docs/evidence/M14c/run-gate.sh reference
```

The runner uses locked dependencies, clears AI credential variables, sets bounded
30-second backend deadlines, serializes shared development fixtures, and runs
pytest with plain assertions and private logs. Sanitized transcripts, JUnit,
exits and expected-case comparisons are retained in `docs/evidence/M14c/`.
Tokens, confidential secrets, backup payloads and private continuity proofs are excluded.

## Executed qualification

| Check | Result / evidence |
|---|---|
| Local `make check` | PASS, exit 0: 1,081 tests; 168 real-service cases intentionally skipped. Ruff, strict mypy, secret/baseline/profile checks, OpenAPI and licenses pass. Skips establish no integration claim. [Candidate transcript](../evidence/M14c/check.log) and [release-metadata rerun](../evidence/M14c/check-release.log) both pass, exit 0. |
| External provider | PASS, exit 0: all 32 expected cases, 507.89 seconds; zero failures/errors/skips. [JUnit](../evidence/M14c/external.xml), [transcript](../evidence/M14c/external.log). |
| Fresh reference | PASS, exit 0: all 8 expected M13 cases, 1,504.91 seconds; real bootstrap, Explorer, fixture loads, backups, recovery and release audit. [JUnit](../evidence/M14c/reference.xml), [transcript](../evidence/M14c/reference.log). |
| Applicable regressions | PASS: 122 distinct expected cases. First attempt: 79 passed, one fixture setup error, exit 1 (1,757.62 s). Corrected continuation: 43 passed, exit 0 (2,319.04 s). [Combined successful JUnit](../evidence/M14c/regression-combined.xml), [first attempt](../evidence/M14c/regression-part1.xml), [continuation](../evidence/M14c/regression-part2.xml). |
| Built candidate workflow | PASS, exit 0: fresh initialization, approved browser enrollment, normal API/ChangeSet/context/revocation inside the built candidate image with a read-only root filesystem. [Result](../evidence/M14c/image-workflow-tested.json), [runner](../evidence/M14c/release-image-workflow.py). |
| Image/security audit | PASS on tested image; no findings, no AI/development packages or dynamic imports. [Audit](../evidence/M14c/release-audit-tested.json). |
| Released artifact | PASS: complete seven-layer amd64 archive was imported; its real browser/API workflow and security audit pass. [Workflow](../evidence/M14c/image-workflow-release.json), [audit](../evidence/M14c/release-audit-release.json). Wheel installation/contract passes and all 30 runtime versions match the tested image: [wheel check](../evidence/M14c/wheel-check.json). |
| Upstream CI | PASS: both main/tag Development checks runs at released source complete successfully. [Run evidence](../evidence/M14c/ci-release.json). CI does not substitute for the retained real-service gates. |
| Real TLS trust | PASS: reference `oidc-check` exit 0 with explicit CA; a fresh process without it rejects the certificate with sanitized `oidc_identity_unavailable`, exit 4. [Positive](../evidence/M14c/oidc-reference.json), [negative](../evidence/M14c/oidc-untrusted-ca.json). |

[Case comparison](../evidence/M14c/case-comparison.json) checks actual node IDs
against lists captured before execution. The corrected continuation used
`bash /tmp/c1-m14c-regression-tail.sh regression`, generated from the runner
with paths M08, M09, M09a, M10, M11, M12 and M14b only. The committed runner
now accepts those explicit paths after `regression` to reproduce the same
continuation. Both original and continuation transcripts/exits are retained.
Mandatory failures/skips/missing cases
block qualification. Unit and real-service evidence are recorded separately.

## Acceptance mapping

| ID | Result | Executed evidence |
|---|---|---|
| T01 | PASS | External browser fixture initializes real backends without provider administration; C1 network boundary denies provider-admin/engine connections. |
| T02 | PASS | Wrong first login/provider admin denied; approved explicit browser confirmation; concurrent confirmation and exact-identity crash recovery. |
| T03 | PASS | 14 initialization and 6 enrollment SIGKILL boundaries: real resource creation, lost responses, durable checkpoints; retries preserve resources/grants. |
| T04 | PASS | Repeated initialization, populated restart, immutable namespace/configuration binding; absent state cannot select legacy mode. |
| T05 | PASS | Real Chrome Code callback, refresh enabled/absent, access/session expiry, local CSRF logout, optional provider logout, independent bearer lifetime. |
| T06 | PASS | Signed unit signature/issuer/audience/time/purpose/kind/ID-nonce negatives; real ID-token API rejection, state/PKCE and JWKS/unknown-key failures. |
| T07 | PASS | Real registered browser client rejects password/client-credentials and implicit/hybrid grants; only Code+S256 human login. |
| T08 | PASS | External least privilege, denied admin, create/modify ChangeSets, separate submit/review, self-review denial, context/reads, next-request revocation. |
| T09 | PASS | Pending setup allowlist/503 readiness; expired/wrong approvals, concurrent/crashed confirmation; live consistency required before publication. |
| T10 | PASS | Isolated instances/namespaces, restart/outages/delays, real CA trust and signing-key rotation with unchanged identity namespace. |
| T11 | PASS | Real Hydra external and fresh Keycloak reference; unsupported metadata/token capabilities fail explicitly. |
| T12 | PASS | Public state/consistency/online optimize and exclusive recovery operations with standalone application-owned backends. |
| T13 | PASS | Actual cold Terminus storage/PostgreSQL dump, fresh-node restore and guard persistence; backup/guard/verify/release crashes, corruption/version/namespace/stale-proof/outage/changed-grant rejection, explicit verified release. |
| T14 | PASS | All 122 M01–M12/M14b regressions, fresh 8-case M13, legacy-reference compatibility and local M14a/M14b checks pass without AI credentials. |

## Review findings and corrections

This is an implementation self-review, not an independent-agent review.

- OpenFGA protobuf empty defaults and TerminusDB verbose ownership metadata
  required exact semantic/resource reconciliation rather than blindly recreating.
- Opaque-subject ChangeSet attribution needed canonical principal decoding and
  safe provenance IRIs; legacy identifiers remain unchanged.
- Startup identity/restore guards must precede authorization write recovery.
  Read-only schema-crash inspection now explicitly verifies identity first.
- OAuth Basic credentials require form encoding before Basic encoding. Real
  browser tests include reserved-character secrets. Direct provider logout
  redirects conflicted with secure CSP; a trusted signed-out link preserves CSP.
- A first concurrent fixture run interfered with development service outages;
  shared suites now take a process lock. One setup exceeded the old short FGA
  deadline; qualified fixtures explicitly use bounded 30-second deadlines.
- A reference attempt reached 7 passes before audit selected hardcoded Podman/rc1.
  Engine/version detection and a dynamic hashing import were corrected. The
  subsequent fresh reference run passes all 8 cases and the audit.
- An earlier regression run found read-only schema-crash readiness expectations
  needed explicit identity verification; original denied/history assertions remain.
- The later regression run passed 79 cases, then a software loader contacted its
  hardcoded original Keycloak port. The shared configured probe endpoint now
  isolates token acquisition. The failed setup remains an unsuccessful attempt;
  the corrected 43-case continuation passed. The 122 successful cases exactly
  match the expected list, with no duplicates or skipped mandatory cases.

## Compatibility limits and gate outcomes

Only the real tested `c1-v1` Keycloak and `hydra-jwt-v1` Hydra configurations are
provider-qualified. `rfc9068-v1` has signed unit coverage; no real-provider gate
is claimed for it. OIDC compliance alone is insufficient. Public clients,
opaque access tokens, automatic namespace/user migration, agent credentials and
new delegation remain excluded. Optional provider capabilities are explicit;
logout does not promise global invalidation of already-issued bearer tokens.

Qualified full-storage transport requires dedicated application backend
persistence and supervisor writer quiescence. Shared-backend scoped transports,
pre-M14c backup migration, other provider/version/client profiles and NS8-specific
packaging require their own qualification. NS8 is a downstream consumer; its
fixture hostnames are never C1 defaults. No incompatible-storage image rollback
or implicit identity remapping is provided.

**Gate A:** PASS. **Gate B:** PASS, including the published pinned artifact.
All mandatory cases passed; no outstanding gate failure or unexecuted mandatory
case remains. [Source equivalence](../evidence/M14c/source-equivalence.json) confirms
the release changes only contract qualification metadata; authentication,
enrollment, recovery and authorization code matches the full-service candidate.
M14c is VERIFIED. M15 remains unimplemented; no next milestone was started.

## Artifact packaging and publication

The first classic Docker 29 archive export contained manifest references but
omitted layer payloads; it was rejected before publication. The final artifact
uses official Docker Buildx 0.38.0, verified against its release checksum
`4fe4cc38adf48169132749b6ca22a990928db0118e3407584ee553723115d287`.
Its tagged [Apache-2.0 license](../evidence/M14c/licenses/buildx-LICENSE) is retained.
Builder/client configuration lives under private `/tmp` directories because
the normal home configuration is read-only; no global settings were changed.

```sh
DOCKER_CONFIG=/tmp/c1-m14c-tools/docker-config \
BUILDX_CONFIG=/tmp/c1-m14c-tools/buildx-config \
/tmp/c1-m14c-tools/buildx-v0.38.0.linux-amd64 build \
  --platform linux/amd64 --provenance=false \
  -f deployment/reference/Containerfile \
  --build-arg C1_REVISION=d6d9f8614c8dfd52591ec1d2402438f7b6a626f7 \
  --tag localhost/c1:0.1.0rc2 \
  --output type=docker,dest=/tmp/c1-m14c-release/release-image.raw.tar .
docker image load --input /tmp/c1-m14c-release/release-image.raw.tar
gzip -nc /tmp/c1-m14c-release/release-image.raw.tar > IMAGE_ARCHIVE
PYTHONPATH="$PWD" PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" \
  C1_RELEASE_IMAGE=sha256:b1546cbbf032eedf7c3c58cb1b4e371d9aab62aa054a1515aa092ef7a3b0b653 \
  uv run --locked python docs/evidence/M14c/release-image-workflow.py
C1_ENGINE=docker C1_REFERENCE_PROJECT=c1-m14c-reference \
  uv run --locked python scripts/release_audit.py --out RELEASE_AUDIT_JSON
UV_CACHE_DIR="$PWD/.uv-cache" uv build --out-dir /tmp/c1-m14c-release
```

The wheel is installed into an isolated Python 3.13 environment using exported
locked runtime requirements and `uv pip install --no-deps`. The packaged operator
contract and all installed versions are verified. The source/wheel archives were
inspected to exclude private configuration, secrets, caches and browser runtimes.
`gh release create --verify-tag --prerelease` published the seven listed assets;
publication verification compares every server-reported SHA-256 and byte size.
The image is delivered as a pinned downloadable archive, without a registry-tag
claim. [Compatibility instructions](../evidence/M14c/release-compatibility.md)
describe consumption. Artifact availability completes Gate B; downstream host
configuration and production lifecycle remain its supervisor responsibility.
