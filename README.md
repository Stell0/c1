# C1

C1 is planned as an open-source, versioned knowledge framework for people, applications, and external software agents. The intended product uses one shared knowledge repository, attributed claims and evidence, explicit permissions, controlled changes, and deterministic context retrieval. Its required workflows do not depend on an LLM, embeddings, or an AI-provider key. The project requirements are in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md); the proposed architecture is in [MVP_ARCHITECTURE.md](MVP_ARCHITECTURE.md); development proceeds one milestone at a time as recorded in [PLAN.md](PLAN.md).

## What exists today

- Harness: Python project metadata and a lockfile, Make targets for bootstrapping/checking, a clean-start helper, and a GitHub Actions check workflow.
- Model: canonical records, bundled JSON-LD/SHACL profiles, exact lexical values, keywords and time qualifiers, with a verified internal TerminusDB round-trip; see the [M02 report](docs/milestones/M02-report.md).
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

## Milestone status

See [PLAN.md](PLAN.md) for scope and status. Roadmap entries describe future acceptance contracts; they do not imply that the corresponding product features exist or have passed verification. Each milestone has its own plan and evidence report.
