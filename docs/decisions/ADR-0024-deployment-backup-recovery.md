# ADR-0024 — Reference deployment, backup and guarded recovery

Status: accepted (M13 implementation, 2026-10-04).

## Context

M13 must produce a release candidate whose deployment, recovery and acceptance claims are backed by repeatable evidence (PLAN.md §M13; architecture §15; specification F10). Until M13 the C1 service ran from `uv` on a development host next to a stack with loopback-published backends, `start-dev` Keycloak and secrets in environment variables. Backups and restores did not exist. Security state is split: the TerminusDB workflow database holds the journal (scopes, bindings, operations, ChangeSets), while OpenFGA in PostgreSQL holds membership, instance and binding tuples.

## Decision

**Image.** `deployment/reference/Containerfile` builds `localhost/c1:<version>` in two stages:
- a uv 0.12.2 builder runs `uv sync --locked --no-dev --no-editable`;
- the runtime is `python:3.13-slim` (both pinned by amd64 digest).

The runtime holds the virtual environment, the license files and an entrypoint only. The entrypoint copies `/run/secrets/*` to a tmpfs (`/run/c1/secrets`, owned by UID 10001, mode 0400), then runs `setpriv` to UID 10001 with `--no-new-privs`. The root filesystem is read-only. The image is built locally and never pushed.

**Reference deployment.** `deployment/reference/compose.yaml`:
- **Network:** only the nginx TLS proxy publishes a port. Every other service is on a `backend` network declared `internal`, which has no Internet egress; M13-T01 verified this from inside the C1 container. Backend addresses are fixed from a configurable /24, because of the M09a DNS lesson.
- **Keycloak:** runs `start` behind the proxy (`--proxy-headers xforwarded`, `--hostname https://auth.c1.test:18443`, `--hostname-backchannel-dynamic`). The proxy exposes only `/realms/` and `/resources/`.
- **Secrets:** read from files by C1 (`C1_*_FILE`), PostgreSQL (`*_FILE`) and wrapper entrypoints (TerminusDB, Keycloak). OpenFGA has no shell and no file settings, so its datastore password and preshared key come from a mode-0600 env file. Secret values never appear in `compose.yaml`.
- **Settings:** non-secret settings are in an ignored `.env`.

**Private CA trust.** `C1_ISSUER_CA_FILE` makes the token validator and the Explorer's OIDC client trust a private CA for identity requests. httpx clients use `trust_env=False`, so `SSL_CERT_FILE` would be ignored. Python 3.13 enforces strict X.509 checks; test certificates carry Subject and Authority Key Identifiers.

**Bootstrap.** `c1-admin bootstrap` runs once on an empty deployment. In a one-shot `tools` container it creates:
- realm `c1` from `src/c1/admin/realm-c1.json`, with clients `c1-api` and `c1-explorer`;
- the first administrator, with the names and email that Keycloak's user profile requires;
- the OpenFGA store and model, with instance `access_admin` and `schema_admin` for the administrator only;
- both TerminusDB databases, through `Terminus.create_for_deployment`, a create-only path separate from the test-only create/drop.

**Backups (quiesced).** `c1-admin backup`:
1. stops C1;
2. refuses while a security operation is pending;
3. stops TerminusDB and exports its storage volume (`podman volume export`);
4. dumps the `openfga` and `keycloak` databases;
5. writes a checksummed manifest;
6. restarts everything.

**W1 finding.** `terminusdb bundle`/`unbundle` round-trips on the same server, but a bundle references layers that exist only on its source server: unbundling into a fresh server fails with `unknown_layer_reference`. Bundles are therefore not backups.

**Knowledge-only restore.** `c1-admin restore-knowledge`:
- refuses on a pending operation and on profile drift (a profile installed later, or a different version);
- saves a safety copy of the storage;
- starts a temporary, unpublished TerminusDB from the backup on the backend network;
- replaces the live knowledge database with a clone from it (`/api/clone`, full history, same commit IDs);
- appends a `Restore` journal record.

The journal and OpenFGA are untouched, so current bindings keep governing.

**Disaster recovery.** `c1-admin restore-full` restores into a new project and directory: it imports the storage volume, restores both dumps, checks the heads against the manifest, and writes a `Restore` guard record. `Runtime.start` reads the guard once at startup. While it is unreleased, `ready()` is false and the boundary answers 503 to every request.

- `c1-admin dr verify` runs journal recovery, then compares every active journal binding with the live OpenFGA `bound_to` tuples and records the result.
- `c1-admin dr release --accept-security-as-of … --reason …` requires a passing verify and a fresh passing comparison. It records the operator's explicit acceptance, then restarts C1 (stop and start: `restart` refuses because of the exited migration dependency) and starts the proxy.

**OpenAPI, licenses and audit.**
- `scripts/openapi.py` generates `docs/api/openapi.json` from `app.openapi()`, adding query parameters from the boundary allowlist. It is not served.
- `scripts/license_inventory.py` generates `THIRD_PARTY_NOTICES` and `docs/release/third-party.json` from the locked runtime set and the pinned images' license files (M01 artifacts for the four services).
- `scripts/release_audit.py` checks the image, the compose file, the source and the running deployment.
- `make release-check` runs the OpenAPI and license checks.

## Evidence

- W1 probes (2026-10-04, laptop):
  - the wheel contains its data files;
  - the backends are healthy in production mode with file secrets;
  - egress from the C1 container is unreachable;
  - `uid 10001`, `NoNewPrivs` and a read-only root filesystem are confirmed;
  - a bundle unbundled into a fresh server failed;
  - storage export, clone restore and guarded restore round trips passed.
- Tests: `tests/unit/m13`, and `tests/integration/m13` T01, T03–T06 and T08 on the reference deployment; results are in the M13 report.
- References:
  - [Podman volume export](https://docs.podman.io/en/latest/markdown/podman-volume-export.1.html);
  - [Keycloak reverse proxy and hostname v2](https://www.keycloak.org/server/reverseproxy);
  - [OpenFGA configuration](https://openfga.dev/docs/getting-started/setup-openfga/configure-openfga);
  - [TerminusDB clone API](https://terminusdb.org/docs/).

## Consequences

- C1 serves nothing during a backup; the measured duration is in `docs/operations/limits.md`. There is no online backup.
- A knowledge-only restore is a storage operation, not a reviewed ChangeSet. The journal keeps the audit trail, and reviewed compensating restores remain the tool for individual changes.
- Disaster recovery depends on an operator's explicit acceptance of the security backup time. C1 cannot know about revocations made after the backup.
- The reference files hard-code `c1.test`, `auth.c1.test` and port 18443. Real installations must edit the host names in three places and supply their own certificates.
- The orchestration targets Podman and podman-compose (`C1_ENGINE`, `C1_COMPOSE` allow alternatives); Docker Compose has not been tested.
