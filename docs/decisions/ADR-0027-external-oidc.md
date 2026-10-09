# ADR-0027 — External OIDC application contracts

Status: accepted for implementation under the owner's M14c approval (2026-10-09);
Gate A, Gate B, complete interoperability, and release qualification pending.

## Context

At `ebad219926f547926d9e24059f2129d5970022ff`, bootstrap provisions Keycloak and
application backends in one function. Legacy token/subject/discovery assumptions
restrict independently managed providers. The owner authorized provider-independent
initialization, guarded exact-identity enrollment, and application-owned recovery,
while retaining reference behavior and all authorization invariants.

## Decision

- D1: expose `c1-admin application` with contract version 1, input/output schemas,
  safe JSON/exit categories, and direct application-backend operations. Supervisor
  lifecycle/backup transport stays outside C1. Qualification capabilities stay
  false until real required gates pass.
- D2: fsync protected persistent initialization intent before backend creation;
  use a random ownership marker in database comments/store names. Reconcile
  pinned store/model IDs and exact model semantics. Never recreate a missing
  completed resource. Pin stable identity also in the workflow journal.
- D3: preserve `c1-v1`; add explicit `rfc9068-v1` and `hydra-jwt-v1` profiles with
  signed purpose contracts and no classification fallback. Hydra's signed
  `ext.token_use=access` is required and access-only; `client_id`/`jti` are required.
- D4: trust validated same-origin metadata endpoints without a Keycloak path
  layout; cross-origin endpoints require exact operator-approved HTTPS URLs.
  Disable redirects/proxies and retain TLS/private-CA verification and key checks.
- D5: preserve legacy principal IDs; encode opaque printable ASCII subjects using
  `~` plus unpadded base64url. `~` is disjoint from legacy syntax. No normalization,
  email mapping, truncation, or cross-namespace inheritance is permitted.
- D6: initial browser client uses Code+S256 PKCE and confidential Basic client
  authentication. Configure scopes/audience parameter explicitly. Refresh/logout
  are optional; local logout remains available. Access/ID subjects must match.
- D7: a protected exact-subject approval expires in 60–86,400 seconds. Confirm
  through authenticated Explorer with CSRF. Persist grant intent before writes;
  serialize/reconcile exact grants. Renew only the same identity after grant
  intent starts. Durable workflow audit and live consistency precede readiness.
- D8: application-owned manifests exclude external IdP persistence. Guarded
  recovery requires independently verified namespace/client/subject attestation,
  a normal fresh user token, compatible data/model, explicit authorization-snapshot
  acceptance, bounded verification lifetime, and fresh exact tuple/head checks.
- D9: initial non-Keycloak fixture is Ory Hydra 2.3.0, image digest
  `sha256:b94007e19a1f7f78157e7f4ea340da8a55b5f104a0f1198755c256f38ef32b4b`.
  Its supervisor-owned synthetic login/consent service does not mock OIDC: Hydra
  implements discovery, code exchange, signed tokens, PKCE and refresh. Reference
  Keycloak uses the existing committed 26.7.4 digest. Record complete matrices
  and limitations in the M14c report.

## Evidence

Source inspection and live development probes confirmed database metadata needs
`GET /api/db?verbose=true` and exact `path`; OpenFGA emits empty protobuf defaults
that must be normalized without removing relation semantics. Repeated initialization
then retained owned IDs. A real Chromium/Hydra enrollment test passed; this is
partial evidence, not either complete gate.

Normative sources checked 2026-10-09:
[RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html),
[OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html),
[Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html),
[RP-Initiated Logout](https://openid.net/specs/openid-connect-rpinitiated-1_0.html),
and [Hydra 2.3.0 release/source](https://github.com/ory/hydra/releases/tag/v2.3.0).

## Consequences

External deployments require no IdP administration and cannot bootstrap permissions
from arbitrary first login. The supervisor must preserve protected initialization
state, a shared writer lock, independent namespace evidence, registered client,
secret transport and actual application snapshots. New reference bootstrap shares
the initializer and backs up its state volume. Legacy reference backups without
that metadata need a separately documented safe upgrade path; they cannot be
silently asserted to contain namespace continuity. Mandatory failures/non-execution
block qualification; M15 remains blocked through verification and release.
