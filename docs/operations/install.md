# Installing the reference deployment

## Requirements

- A Linux host with Podman 5 and `podman-compose` (tested: Podman 5.8.2, podman-compose 1.x), or a compatible Docker Compose setup with `C1_ENGINE=docker` and `C1_COMPOSE="docker compose"`.
- At least 4 vCPU and 4 GiB of memory free for the stack (memory limits total about 4.8 GiB; measured use is lower, see [limits.md](limits.md)).
- `uv` to build and run `c1-admin` from a checkout, or the `c1` wheel installed in a Python 3.13 environment.

The deployment pulls these images by digest; nothing else is fetched at runtime: TerminusDB 12.0.7, PostgreSQL 17, OpenFGA 1.21.0, Keycloak 26.7.4, nginx 1.30.5 (stable-alpine), and the locally built `localhost/c1` image. The digests are in `deployment/images.json` and `deployment/reference/images.json`.

## Build the C1 image

```sh
podman build -f deployment/reference/Containerfile -t localhost/c1:0.1.0rc1 .
```

The image contains only the locked runtime dependencies and the `c1` package. It runs as UID 10001 with a read-only root filesystem; its entrypoint copies mounted secrets to a private tmpfs and drops root privileges. The project does not publish images.

## Settings

Non-secret settings live in `deployment/reference/.env` (read by Compose; not committed):

| Setting | Default | Meaning |
|---|---|---|
| `C1_INSTANCE_ID` | `c1` | Instance identifier (authorization object `instance:<id>`) |
| `C1_INSTANCE_IRI_BASE` | `urn:c1:instance:ref:` | Namespace of minted canonical IDs; choose once, never change |
| `C1_QUERY_TIME_BUDGET_MS` | `10000` | Per-request query budget (max 30000) |
| `C1_BACKEND_TIMEOUT_S` | `5` | OpenFGA and identity client timeout (1–30) |
| `C1_FGA_DEADLINE` | `3s` | OpenFGA server deadline; raise together with the client timeout on slow hosts |
| `C1_REF_BIND`, `C1_REF_PORT` | `127.0.0.1`, `18443` | Where the TLS proxy listens |
| `C1_REF_NET_PREFIX` | `10.89.251` | The backend network's /24 |

The public names are `c1.test` (C1) and `auth.c1.test` (Keycloak) on port 18443 in the reference files. For a real installation, edit the host names in `compose.yaml`, `nginx.conf.template` and `src/c1/admin/realm-c1.json` consistently, and use certificates from your own CA.

## First start

```sh
uv run --locked c1-admin bootstrap            # add --admin-email for the first administrator
```

Bootstrap runs once on an empty deployment:

1. It generates random secrets into `deployment/reference/secrets/` (directory mode 0700) and, if none exist, a throwaway test CA and server certificate in `certs/`.
2. It starts PostgreSQL, TerminusDB, OpenFGA and Keycloak on the internal network.
3. In a one-shot `tools` container it creates the Keycloak realm `c1` (clients `c1-api` and `c1-explorer`, no other users), the first administrator `c1admin` with the password in `secrets/admin_password` (to be changed at first sign-in), the OpenFGA store and model, and both TerminusDB databases with the core profile. The administrator receives the instance roles `access_admin` and `schema_admin`, nothing else.
4. It records the OpenFGA store and model identifiers in `state/c1.env` and `state/bootstrap.json` (no secrets), then starts C1 and the proxy.

Sign in to the Explorer at `https://c1.test:18443/explorer/`. API clients obtain access tokens from `https://auth.c1.test:18443/realms/c1` (register service clients in Keycloak; give them the `c1-api` audience and a `c1_principal_kind` claim of `service`).

## Network exposure

Only the proxy publishes a port. All other services are on the `backend` network, which is declared `internal`: containers there cannot reach the Internet, and the host cannot reach their ports. The proxy serves `/v1/` and `/explorer` for `c1.test`, and only `/realms/` and `/resources/` for `auth.c1.test`; the Keycloak admin console is not exposed.

## Secrets and rotation

| File in `secrets/` | Used by |
|---|---|
| `terminus_password`, `fga_token`, `cursor_secret`, `explorer_client_secret` | C1 (read through `C1_*_FILE` settings) |
| `postgres_password`, `fga_db_password`, `keycloak_db_password` | PostgreSQL roles, OpenFGA, Keycloak |
| `keycloak_admin_password` | Keycloak bootstrap administrator (master realm) |
| `admin_password` | Initial password of the first C1 administrator |
| `openfga.env` | OpenFGA datastore password and preshared key; OpenFGA has no file-based secret settings |

To rotate a C1 secret, change it at its source (for example the OpenFGA preshared key in `openfga.env` and `fga_token` together), replace the file, and restart the affected containers. Database passwords must also be changed in PostgreSQL. Keep a separate, protected backup of the secrets directory: data backups do not contain it.

## Health

`GET /v1/readyz` is the only unauthenticated route. It is 200 only when identity discovery and keys, OpenFGA, the journal, the installed profiles and the writer lock are all available and no security operation is pending; otherwise 503. The container health check tests only that the service listens.
