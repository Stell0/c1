# C1

C1 is planned as an open-source, versioned knowledge framework for people, applications, and external software agents. The intended product uses one shared knowledge repository, attributed claims and evidence, explicit permissions, controlled changes, and deterministic context retrieval. Its required workflows do not depend on an LLM, embeddings, or an AI-provider key. The project requirements are in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md); the proposed architecture is in [MVP_ARCHITECTURE.md](MVP_ARCHITECTURE.md); development proceeds one milestone at a time as recorded in [PLAN.md](PLAN.md).

## What exists today

- Harness: Python project metadata and a lockfile, Make targets for bootstrapping/checking, a clean-start helper, and a GitHub Actions check workflow.
- Model: canonical records, bundled JSON-LD/SHACL profiles, exact lexical values, keywords and time qualifiers, with a verified internal TerminusDB round-trip; see the [M02 report](docs/milestones/M02-report.md).
- Security: authenticated HTTP boundaries, OIDC tokens, current-binding authorization, durable security operations and crash recovery passed the real-service gate; see the [M03 report](docs/milestones/M03-report.md).
- Baseline: repository-local, attributed specification and architecture documents, with the software-use-case extension recorded separately.
- Checks: local code-quality, type, test, secret-hygiene, and baseline-consistency checks.
- CI: the pinned GitHub Actions workflow passed; deliberate canary failure and restored success are verified in the [M00 report](docs/milestones/M00-report.md).
- Conventions: milestone plan and report guidance and templates are provided.
- License: Apache-2.0 project license and a third-party notices placeholder are present.

## Run the harness

Prerequisites: Git, `uv` 0.12 or later, GNU Make, and network access for the first dependency sync. From the repository root:

```sh
make bootstrap
make check
make clean-start
```

`make bootstrap` installs the locked development environment, and `make check` runs the local checks. `make clean-start` requires a clean, committed checkout. To check an ephemeral snapshot of the current uncommitted work, run `bash scripts/clean_start.sh --worktree`. None of these commands needs an AI-provider credential.

## Isolated infrastructure proofs

M01 adds a local experimental stack and probes outside the product package.
With Podman 5.x, podman-compose, and about 4 GB free RAM:

```sh
make stack-up
make inventory
C1_STACK=1 make probe
make stack-down
```

First startup downloads pinned images and creates private random credentials in
ignored `deployment/.env`. Services bind only to loopback. Tests use synthetic
records, pause/restart the owned OpenFGA service, and remove their databases and
stores. Run this gate sequentially on the dedicated development stack.
`make stack-down` preserves volumes; `make stack-reset` deletes only this stack's
development volumes. Default `make check` skips these real-service tests.
The [M01 plan](docs/milestones/M01.md) records scope and limitations.

## Canonical model development

M02 adds a versioned profile in `profiles/core/` and the synthetic fixture in
`fixtures/core-knowledge/`. The model has no HTTP endpoint or authorization bypass.
Profile and pure-model checks are part of `make check`; the full real-service
regression gate is `C1_STACK=1 make integration`. See the
[M02 plan](docs/milestones/M02.md) for the supported subset and accepted decisions,
and the [M02 report](docs/milestones/M02-report.md) for executed evidence.

## Identity and authorization (M03)

The current M03 implementation adds bearer-token authentication, a current
OpenFGA authorization plane, workflow-journaled scope and binding operations,
and readiness checks for identity, authorization, and storage services. The
probe routes are disabled by default and limited to synthetic records; ordinary
knowledge CRUD remains out of scope. M03 is **VERIFIED**: 185 local tests and
39 real-service integration tests passed, including historical access denial,
three process crash points and identity/authorization outages. See the
[M03 report](docs/milestones/M03-report.md) for evidence and limits.

For a local development demonstration, `make stack-up` creates the pinned
services and synthetic identity fixtures; `make api-up` starts the loopback API
with probe routes explicitly enabled. This helper is for development only.
The following uses the generated private credentials without printing a token:

```bash
uv run --locked python - <<'PY'
import httpx
from probes.config import environment
settings = environment()
with httpx.Client(timeout=10, trust_env=False) as client:
    response = client.post(settings["C1_ISSUER"] + "/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "c1-dev-tests",
        "client_secret": settings["C1_DEV_TESTS_SECRET"],
        "username": "alice", "password": settings["C1_USER_ALICE_PASSWORD"],
    })
    response.raise_for_status()
    identity = client.get("http://127.0.0.1:18000/v1/whoami", headers={
        "Authorization": "Bearer " + response.json()["access_token"],
    })
    identity.raise_for_status()
    print(identity.json())
PY
make api-down
```

The reproducible two-administrator re-scope demonstration, including denial at
both head and the older revision, is
`C1_STACK=1 uv run --locked pytest -q tests/integration/m03/test_t04_historical.py`.
The full `C1_STACK=1 make integration` gate additionally runs real API process
crashes and service outages, so run it without another development API process.
Stop the services with `make stack-down` when finished; it preserves volumes.

## Reviewed changes and history (M04)

M04 adds ChangeSet drafts, validation, independent review, atomic application,
authorized resource reads, and resource history. The
[M04 report](docs/milestones/M04-report.md) records its verified gate; the
[M04 API notes](docs/milestones/M04-api.md) describe the request contract and
access rules. Ordinary knowledge writes use ChangeSets. The synthetic probe
routes remain a development test surface.

To run the reviewed-write demonstration against the pinned local services:

```sh
make stack-up
uv run --locked python -m scripts.demo_m04
make stack-down
```

The script creates and cleans up isolated test databases and an OpenFGA store.
It obtains real synthetic user tokens without printing them, then prints the
ChangeSet receipt and the authorized history listing. It does not need a running
`make api-up` process.

## Shared identity and queries (M05)

M05 adds a deterministic query API over the one shared repository. Authenticated
clients can use `/v1/catalog`, `/v1/entities`, `/v1/entities/search`,
`/v1/assertions`, `/v1/sources`, `/v1/evidence`, `/v1/export`, and an entity's
`/neighborhood` route. Simple filters are URL parameters; combined entity
filters use the strict JSON body of `POST /v1/entities/search`. Every result is
selected under current resource bindings, including when reading an older
knowledge revision. Cursors pin the content revision and are reauthorized on
continuation. Query limits and explicit failure behavior are in
[the M05 plan](docs/milestones/M05.md) and [execution report](docs/milestones/M05-report.md).

The synthetic directory fixture uses one Person ID for Company A and Company B
and protects each contact assertion independently. To load it into the configured
local development database and see the four principals' authorized IDs and
counts:

```sh
make stack-up
uv run --locked python scripts/load_fixture.py --fixture directory --database c1_m03_dev_knowledge
uv run --locked python scripts/demo_m05.py
make stack-down
```

The loader uses local development credentials and authenticated C1 APIs. Its
service principal authors the knowledge ChangeSet; a separate reviewer approves
it. Use a fresh local stack for a fresh fixture load.

## Scoped documents (M06)

Authenticated clients can list and search `/v1/documents`, inspect a document
and its ordered `/parts`, and request `/render`, `/export`, or `/history`.
Use `/v1/documents/by-id?document_id=` for detail lookup of arbitrary canonical
IRIs, including IDs that end in an operation suffix.
Reconstruction includes only currently readable parts, including for historical
revisions. Text preserves supplied Unicode code points and whitespace; each
returned part includes its UTF-8 SHA-256 digest. Markdown rendering neutralizes
links and HTML, and labels source-code excerpts explicitly.

The [M06 plan](docs/milestones/M06.md) defines the flat part model, ordering,
evidence selectors, and limits. The [API notes](docs/milestones/M06-api.md)
describe request and response contracts. To run the synthetic demonstration:

```sh
make stack-up
uv run --locked python scripts/load_fixture.py --fixture scoped-document --database c1_m03_dev_knowledge
uv run --locked python scripts/demo_m06.py
make stack-down
```

Use a fresh local stack for a fresh fixture load. The loader uses the ordinary
authenticated ChangeSet path with separate author and reviewer credentials.

## Consumer-ready context (M07)

M07 adds the authenticated, read-only `POST /v1/context` path. Versioned local
data profiles select authorized paths and produce Markdown plus matching
structured facts, excerpts, citations, qualifiers, gaps, and continuation
bounds. Exact keyword filters retain M05 behavior; topic resolution is a
separate explicit mode. Context rendering uses no model or provider credential.
The full M07 acceptance gate is still in progress; see the
[M07 plan](docs/milestones/M07.md), [API notes](docs/milestones/M07-api.md),
and [execution report](docs/milestones/M07-report.md) for current scope and
verification status.

## Milestone status

See [PLAN.md](PLAN.md) for scope and status. Roadmap entries describe future acceptance contracts; they do not imply that the corresponding product features exist or have passed verification. Each milestone has its own plan and evidence report.
