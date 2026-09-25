# C1

C1 is planned as an open-source, versioned knowledge framework for people, applications, and external software agents. The intended product uses one shared knowledge repository, attributed claims and evidence, explicit permissions, controlled changes, and deterministic context retrieval. Its required workflows do not depend on an LLM, embeddings, or an AI-provider key. The project requirements are in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md); the proposed architecture is in [MVP_ARCHITECTURE.md](MVP_ARCHITECTURE.md); development proceeds one milestone at a time as recorded in [PLAN.md](PLAN.md).

## What exists today

- Harness: Python project metadata and a lockfile, Make targets for bootstrapping/checking, a clean-start helper, and a GitHub Actions check workflow.
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

## Milestone status

See [PLAN.md](PLAN.md) for scope and status. Roadmap entries describe future acceptance contracts; they do not imply that the corresponding product features exist or have passed verification. Each milestone has its own plan and evidence report.
