# External OIDC installation and interoperability

M14c adds provider-independent application interfaces. Qualification is recorded
in [the M14c report](../milestones/M14c-report.md); until both gates and release
are recorded, these interfaces are a development candidate. Gate A permits
external-provider integration testing. Gate B is required for downstream
production qualification. No semantic extension or AI credential is required.

## Ownership and provider checklist

C1 owns knowledge, workflow, authorization, initialization, and enrollment.
The provider owns authentication and its identity namespace. The supervisor
owns client registration, networking/TLS, credentials, persistent storage,
container/service lifecycle, writer quiescence, and backup transport. C1 does
not register clients or administer external users/realms. Provider
administrators receive no implicit C1 permissions.

Register a confidential client with **Authorization Code only**, PKCE S256,
`client_secret_basic`, and the exact `<Explorer-origin>/explorer/callback` URI.
Disable password, implicit, and client-credentials grants on that browser
client. Refresh is optional. The initial implementation supports a protected
client secret; it does not support public clients or dynamic registration.

Verify discovery, the exact issuer, supported signed ID tokens (RS256/ES256),
API JWT audience/purpose/classification, subjects, TLS trust, optional refresh,
and optional logout. OIDC compliance alone does not establish API token
compatibility. Ensure the API audience differs from the Explorer client ID;
ID tokens must never be API credentials. Document public versus pairwise
subjects and preserve the client/sector registration that determines them.

## Configuration contract version 1

Reuse C1 environment settings and `*_FILE` secret delivery. Secret files must
be absolute regular non-symlink files with mode 0400 or 0440. Never put
credentials into diagnostic JSON, command lines, source, or ordinary logs.

Example non-secret settings (replace every deployment value):

```sh
C1_IDENTITY_MODE=external
C1_OIDC_CONFIG_VERSION=1
C1_INSTANCE_ID=knowledge
C1_INSTANCE_IRI_BASE=urn:example:knowledge:
C1_INITIALIZATION_FILE=/var/lib/c1/private/initialization.json
C1_LOCK_PATH=/var/lib/c1/writer.lock
C1_ISSUER=https://identity.example/tenant
C1_ISSUER_ALIAS=organization
C1_AUDIENCE=c1-api
C1_OIDC_TOKEN_PROFILE=c1-v1
C1_TERMINUS_URL=http://terminusdb:6363
C1_FGA_URL=http://openfga:8080
C1_ORGANIZATION=admin
C1_KNOWLEDGE_DATABASE=c1_knowledge
C1_WORKFLOW_DATABASE=c1_workflow
C1_EXPLORER_ENABLED=true
C1_EXPLORER_ORIGIN=https://knowledge.example
C1_EXPLORER_CLIENT_ID=c1-explorer
```

Deliver `C1_TERMINUS_PASSWORD_FILE`, `C1_FGA_TOKEN_FILE`,
`C1_CURSOR_SECRET_FILE`, and `C1_EXPLORER_CLIENT_SECRET_FILE` separately.
Use `C1_ISSUER_CA_FILE` for an explicitly trusted private CA; TLS verification
is never disabled. External issuers require HTTPS except loopback test fixtures.

Discovery endpoints on the trusted issuer origin may use different paths.
Cross-origin endpoints require exact HTTPS URLs in the operator-owned JSON
array `C1_OIDC_ENDPOINT_URLS`; metadata cannot extend this list. Credentials,
queries, fragments, untrusted redirects, and token-supplied signing-key URLs
are rejected. Configure only endpoints whose ownership/trust was verified.

`C1_EXPLORER_SCOPES` defaults to `openid`; add `offline_access` only when
qualified. `C1_EXPLORER_AUDIENCE_PARAMETER` is `none` by default, or explicitly
`resource`/`audience` for a provider requiring that authorization parameter.
Its value is the configured API audience. Session idle/max lifetimes use
`C1_EXPLORER_SESSION_IDLE_S`/`C1_EXPLORER_SESSION_MAX_S`.

For standard RP-initiated provider logout, set `C1_EXPLORER_LOGOUT_MODE=rp-initiated`
and register `<Explorer-origin>/explorer/signed-out` as the exact post-logout URI.
Only the validated ID token is used as an IdP logout hint, never an API token.
Local logout first renders a signed-out page. Follow its **Sign out of identity
provider** link to complete RP logout; this avoids relaxing Explorer's CSP for
cross-origin form redirects. The link targets only the trusted discovery endpoint.
`local` ends only C1's session; `backchannel` retains reference Keycloak behavior.
Provider logout requires its advertised trusted endpoint; absence always permits
local termination. The provider's session/refresh revocation behavior must be
qualified separately.

## Explicit access-token profiles

Every profile validates signature, approved algorithm/key, exact issuer, API
audience, subject, expiration, issued-at, and not-before when present. Keys are
selected only through trusted discovery/JWKS. No profile accepts opaque tokens,
unsigned tokens, ID tokens, forwarded identity, or an unclassified principal.

| Profile | Signed access-purpose contract | Principal classification |
|---|---|---|
| `c1-v1` | Payload `typ` is `Bearer`; existing C1 issuer contract. | Mandatory `c1_principal_kind` exactly `human` or `service`; mapping cannot be overridden. |
| `rfc9068-v1` | Header `typ` is `at+jwt` or `application/at+jwt`; nonempty signed `client_id` and `jti`. | Explicit configured claim and exact value mapping. Unit validation is implemented; real-provider qualification remains in the report. |
| `hydra-jwt-v1` | Hydra JWT header `typ=JWT`, signed `client_id`/`jti`, and signed `ext.token_use=access`. This marker must be issued **only** in access-token session claims, never ID-token claims. | The configured classification claim is read from signed `ext`; no default-human fallback. |

For the two configurable profiles, `C1_PRINCIPAL_KIND_CLAIM` defaults to
`c1_principal_kind`; `C1_PRINCIPAL_KIND_MAPPING` is a JSON string mapping,
defaulting to `{"human":"human","service":"service"}`. Only explicitly
listed values classify principals. The issuer must control these claims;
user-editable/provider-administrator role claims are unsuitable. Classification
does not grant permissions. A `human` token may be operated by software and
retains that user's attribution and current C1 permissions.

The normative basis is [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html),
[OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html), and
[OIDC Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html).
The Hydra profile is an explicit provider contract, not a claim of RFC 9068
conformance. Real fixture versions/settings/results belong in the report.

## Initialization and initial administration

Provision a persistent **mode-0700** directory for `C1_INITIALIZATION_FILE`.
The state file is mode 0600 and is application-owned backup material. Operator
and writer processes must use the same persistent `C1_LOCK_PATH`; stop the
writer before initialization or recovery. This interface does not stop services.

```sh
c1-admin application contract
c1-admin application oidc-check
c1-admin application state
c1-admin application initialize --namespace-id independently-verified-namespace-id
```

The supervisor must independently establish and retain the provider namespace
identifier. It is not just the issuer URL or signing-key fingerprint. Initialization
persists intent before writes, pins uniquely owned resources, and reconciles
uncertain responses. It never adopts ambiguous databases/stores, resets existing
state, or grants an account. Retrying preserves IDs and data; missing owned
resources after their completed step are refused rather than recreated.

Store the returned `fga_store`/`fga_model` as `C1_FGA_STORE`/`C1_FGA_MODEL` in
runtime configuration. State distinguishes empty, partial, awaiting enrollment,
approved, enrolling, and complete. An incompatible configuration is refused.
The local state and immutable workflow identity binding preserve the instance,
IRI base, issuer/alias, audience, token/classification profile, and backend IDs.
Changing identity namespace does not migrate permissions.

Approve the exact existing account through the protected local operator interface:

```sh
c1-admin application enrollment-approve \
  --issuer https://identity.example/tenant --subject exact-opaque-subject \
  --operator deployment-operator --expires-in 3600
```

Start C1 and direct the approved user to `/explorer/login`. Until enrollment is
confirmed, C1 exposes only guarded setup/login/callback/assets/confirmation and
local logout; protected operations are unavailable and `/v1/readyz` returns 503.
The callback validates ID-token nonce/signature/audience and the normal API
access token, including matching subjects. A wrong first login is refused.

The approved user explicitly confirms enrollment with session/CSRF protection.
Only instance `access_admin` and `schema_admin` are granted. No content-read
bypass is granted. Durable audit, live authorization, schema and consistency
checks precede guard removal. Further administrators use ordinary authorized
C1 administration. Configuration cannot reopen enrollment.

Approval lasts 60–86,400 seconds. `enrollment-cancel` or a replacement approval
is permitted before grant intent starts. After interruption during grants, only
renewal of the **same** approved issuer/subject is allowed; complete reconciliation
without substituting an identity. Concurrent confirmations cannot duplicate grants.

Ordinary API access uses appropriately obtained user access tokens and current
C1 permissions. Explorer session cookies/refresh tokens/client secrets are never
exported for outside clients. `/v1/setup/identity` and `/v1/setup/confirm` are
guarded setup operations, not an agent protocol.

## Subjects, sessions, and compatibility

Legacy IDs `user:<alias>.<subject>` are unchanged. Printable opaque ASCII OIDC
subjects up to 255 characters that need encoding use `user:<alias>.~<base64url>`
over exact subject bytes. `~` is outside legacy syntax, preventing collisions.
Subjects remain case-sensitive; email/username never replace them. Existing
legacy subject syntax remains supported without silently renaming principals.

Local logout ends the C1 session even if provider logout is absent/unavailable.
The existing reference provider's server-side logout behavior is retained;
other provider logout must be specifically qualified. Refresh-token revocation,
provider-session logout, and already-issued bearer expiry are distinct. C1 does
not promise global token/session invalidation. See
[OIDC RP-Initiated Logout](https://openid.net/specs/openid-connect-rpinitiated-1_0.html).

Operator JSON carries `contract_version=1`. Exit 0 means command success, 2
means refused/invalid input, 3 means inconsistent state, and 4 means unavailable
or failed operation. The contract exposes schemas and qualification capabilities.
`state` inventories do not establish readiness: check live `/v1/readyz`. A
bootstrap receipt, model ID, or apparent browser login alone never passes a gate.
Qualification flags describe the pinned release and its `qualified_token_profiles`,
not every implemented profile or a particular installation. A supervisor must
verify `qualification_release` is published, match its compatible provider/backend
profile, and check the live installation state/readiness before enabling functions.
`C1_OPERATOR_TIMEOUT_S` bounds a command to 30–3,600 seconds (default 300);
uncertain writes retain durable intent for reconciliation rather than blind retries.

Legacy reference installations with no workflow identity binding retain their
existing configuration and authorization behavior when the new state volume is
empty. New installations and all external installations require their durable
binding/state; removing their file cannot select this compatibility path. Stop
the writer, preserve the old volumes/configuration, upgrade the application and
reference recipe together, verify live consistency/readiness, and make a fresh
full backup with the updated tooling before recovery. Pre-M14c backups lacking
application state require a separately qualified migration; do not synthesize
external identity continuity from legacy grants. No automatic
cross-namespace migration or incompatible persistent-storage image rollback is
provided. See [external recovery](external-oidc-recovery.md).

NS8, Kubernetes, and other supervisors consume these same contracts. NS8 test
hostnames and packaging conventions are not C1 defaults or dependencies.
