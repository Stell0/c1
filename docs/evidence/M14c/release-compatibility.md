# C1 0.1.0rc2 compatibility

Versioned interfaces: `c1-admin application contract` (contract/configuration v1), external full-storage backup manifest v2, existing C1 API/Explorer. Qualified access-token profiles are `c1-v1` (Keycloak 26.7.4) and `hydra-jwt-v1` (Ory Hydra 2.3.0). `rfc9068-v1` is unit-tested and requires separate real-provider qualification.

Required services are the repository-pinned TerminusDB 12.0.7, OpenFGA 1.21.0 and PostgreSQL 17 authorization persistence. The OCI image is Linux amd64. The wheel requires Python 3.13 and the exact runtime dependencies in `uv.lock`; no AI credential or vector service is needed. A deployment supervisor independently supplies these services, OIDC registration/configuration, trust/certificates, secrets, persistent initialization identity and writer lock, and approved administrator issuer/subject.

Verify all assets against `SHA256SUMS`. Import `c1-0.1.0rc2-linux-amd64.docker.tar.gz` with `gzip -dc IMAGE_ARCHIVE | docker image load` (or the equivalent Podman import), then run the immutable image ID in `artifact-pins.json`. This archive is an upstream container artifact, not a claim of a published registry tag. The wheel and source archive are also released assets.

Read `docs/operations/external-oidc.md` and `external-oidc-recovery.md` from tagged source before installation. Run `c1-admin application oidc-check`, initialize with independently verified namespace identity, approve the exact initial administrator, require authenticated explicit browser confirmation, and check live `/v1/readyz`. A receipt or contract capability does not establish installation readiness.

Full-storage recovery requires dedicated application-owned persistence, writer quiescence, backup integrity, retained stable instance/namespace/client registration, independent operator continuity evidence and a fresh normal user token. Never restore the external provider database or remap subjects by email. Check the milestone report for qualification evidence and limitations. Deployment integrations, including NS8, must qualify their host-specific lifecycle and routing; no platform-specific C1 code is required.
