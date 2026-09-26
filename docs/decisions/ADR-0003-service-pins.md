# ADR-0003 — Pinned reference services

**Status:** accepted within the owner's M01 implementation request, 2026-09-26.

## Decision

Use the community service artifacts pinned in `deployment/images.json` and
`deployment/compose.yaml`: TerminusDB v12.0.7, OpenFGA v1.21.0, Keycloak 26.7.4,
and PostgreSQL 17.11 (the pinned `17-alpine` manifest). Manifest, platform and
configuration digests are recorded separately. The executable inventory compares
actual local images with those pins and records primary license provenance.

The [inventory](../evidence/M01/inventory.md) and bundled license texts identify
actual artifacts, Python packages and notices. Main project license text is
extracted when present. When checked image paths lack it, use the pinned source
tag's text and hash, explicitly recording the fallback. This corrects the
provisional plan's assumption that every image contains its primary license;
it does not claim a complete image redistribution license bundle. M13 must
inspect all redistributed base-system and transitive components before packaging.

Use Podman 5.7.0 with podman-compose 1.5.0. All published ports bind to loopback;
PostgreSQL has no host port. Generate random development credentials into ignored
`deployment/.env` with mode 0600. No production deployment is supplied. The
Keycloak realm has a public PKCE client; M01 verifies startup and discovery only,
not login/token validation (M03). PostgreSQL supports identity/authorization,
not knowledge or vectors. No image is rebuilt or distributed by this milestone.

OpenFGA uses PostgreSQL and preshared service authentication. Its query caches
remain disabled, and every probe check/binding read requests
`HIGHER_CONSISTENCY`. The client timeout is two seconds. Service pause and kill
experiments demonstrate denial followed by successful recovery. Resource bindings
are required to match exactly one current journal scope before content is read.

TerminusDB uses basic authentication. Exclude the upstream compose example's
`TERMINUSDB_INSECURE_USER_HEADER`, vectorlink and model-backed change-request
components. Set an empty plugin directory. No LLM account, embedding model or
AI-provider credential is used. The product marker package still has no runtime
dependencies; these are isolated development probes.

## Sources and verification

Version-tagged source/license URLs and hashes are in `deployment/images.json`.
The following official references were checked during execution:

- [TerminusDB v12.0.7 compose example](https://github.com/terminusdb/terminusdb/blob/v12.0.7/docker-compose.yml)
  identifies upstream components deliberately omitted here.
- [OpenFGA consistency](https://openfga.dev/docs/interacting/consistency)
  describes consistency preferences; actual revocation and rebinding are tested
  against the pinned server, not inferred from the documentation.
- [Keycloak container guide](https://www.keycloak.org/server/containers)
  documents realm import, health support and the development startup mode.

`make stack-up` uses `up -d` plus HTTP readiness with a 180-second deadline because
this compose provider does not support `up --wait`. T01 validates inventory and
configuration; T05 validates freshness and live faults. See the M01 report for
executed commands and gate outcomes. These service pins authorize no M02/M03
feature implementation.
