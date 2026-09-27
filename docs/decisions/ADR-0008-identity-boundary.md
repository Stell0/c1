# ADR-0008 — Trusted identity and HTTP boundary

**Status:** M03 implementation decision under the owner's implementation request.

## Decision

Use FastAPI and Uvicorn for one configured service. Validate bearer access tokens
with PyJWT and cryptography, using the configured issuer's JWKS. Require signed
issuer, audience, subject, expiry, issued-at, Bearer purpose and human/service
kind; permit RS256 or ES256 only. Validate `nbf` when present. The pinned Keycloak
access tokens omit that optional claim. The 30-second clock leeway also applies
to expiration; the one-second test token must expire beyond that interval.

Identity is trusted issuer alias plus subject, never a request-selected
principal. The supported subject syntax is ASCII letters, digits, dot, underscore
and hyphen; pinned Keycloak UUID subjects satisfy it. Alias validation and the
dot delimiter make this mapping stable within one configured installation.
The principal kind is a trusted issuer claim, not a source of permissions.

JWKS may be cached for 300 seconds; unknown keys trigger a refresh. Readiness
checks discovery and JWKS reachability afresh. Existing trusted keys can validate
already-issued tokens during an identity outage, but readiness remains false.
Only same-origin realm JWKS URLs are accepted. No positive authorization result
is cached.

Configuration is startup environment only. Reject query/header selectors for
database, repository, store, issuer or principal, duplicate query parameters,
and undeclared body fields. Delegation attempts are audited and never affect
identity. Authenticate before parsing protected request bodies; cap streamed
bodies at 1 MiB. Problem Details omit backend errors, tokens and record bodies.
Hidden and nonexistent probe resources have identical 404 responses.

Development realm bootstrap generates private secrets in ignored mode-0600
`deployment/.env`; checked-in realm templates contain no credentials. Direct
password grant clients and synthetic users are test fixtures, not production
identity configuration. Browser login remains M12 work.

## Evidence and sources

- [PyJWT usage](https://pyjwt.readthedocs.io/en/stable/usage.html): registered
  claims, required claims, leeway and JWKS validation.
- [Keycloak administration](https://www.keycloak.org/docs/latest/server_admin/index.html):
  protocol mappers, audiences and service accounts.
- `tests/unit/m03/test_tokens.py` and `test_config.py` cover forged tokens and
  trusted configuration; real Keycloak M03-T01 proves human/service attribution
  and rejects wrong issuer, audience, expired and ID tokens.
- [Dependency review](../evidence/M03/dependencies.md) records installed pins,
  license artifacts and hashes. The M03 report records executed gate results.
