# ADR-0023 — Human Explorer: composition, browser login, rendering and test tooling

Status: accepted (M12 implementation, 2026-10-03).

## Context

M12 must let a person perform the core C1 workflows in a browser without
special database access, an LLM, or a command line ([PLAN.md](../../PLAN.md)
§M12; specification F09). The architecture requires:
- the browser to use the same API and session boundary as other clients (§14);
- authorization code with PKCE and server-managed sessions, with no secrets in
  browser storage or query strings (§6.1);
- no hidden content sent for client-side removal;
- safe rendering of untrusted labels, Markdown, code and schema hints.

ADR-0008 left browser login to M12. ADR-0015 required a browser renderer to
apply its own safe text handling.

## Decision

**Composition.** `c1.web.create_web_app` builds an outer ASGI dispatcher:
- `/explorer` and `/explorer/*` go to the Explorer, a Starlette app;
- everything else goes to the unchanged `create_app` API with its
  `BoundaryMiddleware`.

The Explorer calls the API in-process with `httpx.ASGITransport`, sending
`Authorization: Bearer <the signed-in person's access token>`. Each call passes
through the API's middleware, routes, validation, authorization and audit like
any external client's. A unit test fails if `c1.explorer` imports any `c1`
module other than `c1.config`, `c1.model` (pure records and keyword
normalization, no I/O) and itself. With `C1_EXPLORER_ENABLED` false, the factory
returns the API alone.

**Login.**
- Keycloak client `c1-explorer`: confidential, standard flow only, PKCE S256
  required. Its redirect is `<origin>/explorer/callback`. It carries the
  existing `c1_principal_kind=human` and `c1-api` audience mappers, so its
  access token is an ordinary API token.
- `scripts/bootstrap_security.py` writes its secret to the ignored
  `deployment/.env` as `C1_EXPLORER_CLIENT_SECRET`.
- The Explorer sends `state`, `nonce` and a PKCE challenge. It exchanges the
  code server-side and validates the ID token only to finish login: issuer,
  audience `c1-explorer`, nonce, and signature through the issuer's same-origin
  JWKS, fetched with a bounded `httpx` client that ignores proxy variables.
- It never sends the ID token to the API.
- Logout deletes the server session and ends the identity-provider session with
  a server-side end-session request carrying the refresh token.

**Sessions.** One in-memory table in the single process. Session IDs are 256-bit
random values; only their SHA-256 digests are table keys. Idle timeout is 30 min
and absolute lifetime is 8 h. Access tokens are refreshed server-side when under
30 s remain, and a failed refresh ends the session. A restart ends every session
(owner decision OD4).

Cookies:
- `__Host-c1_session`: `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`.
- `__Host-c1_login`: the login transaction, `SameSite=Lax`, 5 min, consumed
  once at the callback.

The callback answers with a same-site continuation page, not a redirect: a
navigation that a cross-site redirect started does not carry a `Strict` cookie.
Pinned Chromium 153 accepts these `Secure` cookies on `http://127.0.0.1`, a
potentially trustworthy origin (verified by T01–T07).

**Requests.** Reads are `GET`. Every state change is a url-encoded `POST`,
refused with 403 before any API call unless all of these hold:
- a same-origin `Origin` header;
- a live session;
- exactly one matching synchronizer `csrf` field.

Forms are parsed with the standard library, capped at 64 KiB and 400 fields.
Undecodable or control-character input is refused, and so is a duplicate field
where one value is expected. Every response carries:
- `Cache-Control: no-store`;
- `Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`;
- `Referrer-Policy: same-origin`;
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and same-origin
  opener and resource policies.

**Rendering.**
- Jinja2 with autoescape always on and `StrictUndefined`.
- No client-side script at all (owner decision OD1).
- A closed widget set in `templates/widgets.html`. A C1 resource IRI under the
  instance base becomes an internal Explorer link. Any other address is shown as
  text and never fetched.
- Markdown and code are shown as escaped preformatted text; nothing converts
  Markdown to HTML.
- Review state, lifecycle and origin are separate labels.
- Confidence is labelled uncalibrated.
- Code parts are labelled "excerpt" or "complete unit" from the API's part kind.
- API refusals are shown with their status and code; 404 reads "not found, or
  not available to you".

**Public API additions** (also usable by scripts; see
[M12-api.md](../milestones/M12-api.md)): `GET /v1/schema`,
`GET /v1/access-scopes/mine` and `GET /v1/security-operations`. Reading one
security operation is widened from "proposer or destination admin" to "proposer
or an admin of any scope whose approval the operation counts". This matches the
M11 D7 approval rule, under which a lineage-only admin may approve.

**Test tooling (development only).**
- Playwright for Python 1.63.0 with its Chrome Headless Shell 153.0.8010.12
  (build 1243), installed into the ignored `.playwright/`.
- axe-core 4.13.0 (MPL-2.0), vendored under `tests/browser/vendor/` with its
  license and checksum. It is injected only into a separate `bypass_csp` test
  context and is never shipped or served.

## Evidence

- Pins and licenses, re-verified on 2026-10-03 from the installed artifacts:
  [dependency review](../evidence/M12/dependencies.md).
- makako (Rocky Linux 9.8): Chromium needed 13 shared libraries from the
  standard repositories ([package list](../evidence/M12/makako-chromium-deps.txt)).
- Unit tests: `tests/unit/m12/` (login state, cookies, CSRF and origin, forms,
  sessions, escaping, import boundary, configuration, the D7 listings).
- Browser and live tests: `tests/integration/m12/` T01–T07 and the API-addition
  checks; results are in the M12 report.
- OAuth 2.0 Security Best Current Practice (RFC 9700): PKCE for confidential
  clients. RFC 7636 test vector in `test_pkce_challenge_matches_rfc7636_example`.
- Cookie prefixes and SameSite behavior: RFC 6265bis drafts and Chromium
  behavior observed in the tests.

## Consequences

- No new authority exists: forged browser actions get exactly the raw API's
  answer (T04).
- Sessions do not survive a restart, and the session table is per process. M13
  must decide persistence, TLS termination and multi-process deployment.
- `Referrer-Policy: same-origin` replaced the planned `no-referrer`: with
  `no-referrer`, Chromium sends `Origin: null` on same-origin form posts, which
  the origin check must refuse.
- The Keycloak login page is not part of the accessibility audit.
- Rendering without scripts keeps forms simple: creating an entity of a profile
  class is two steps, class first, then that class's fields.
