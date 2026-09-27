# ADR-0001 — Python development baseline

**Status:** accepted for M00 by the owner's implementation request, 2026-09-25.

## Context

The owner selected Python. M00 adds only a package marker and development harness;
no future service, RDF processor, or model SDK is a runtime dependency. The M00
plan selects Python 3.13 because compatibility of the proposed pySHACL path with
3.14 still needs verification in M02. This is a planning constraint, not a claim
that the future dependency has been exercised.

## Decision

Use CPython 3.13 (`requires-python = ">=3.13,<3.14"`, `.python-version = 3.13`),
uv 0.12.2 in CI, and Hatchling 1.27.0. Verification used CPython 3.13.14 on Linux.
The minor-version selector may receive patch updates; reports name the actual
interpreter. Keep a `src/c1` layout with version `0.0.0.dev0` and `py.typed` only.

Commit `uv.lock`. Exact constraints also cover the isolated build dependencies
(Hatchling, editables, packaging, pathspec, pluggy, trove-classifiers), which are
resolved separately from the development group. Regenerate the lock deliberately
when dependencies change. `uv lock --check` precedes `uv sync --frozen`, and all
check commands use `uv run --locked`.

## Evidence

Checked 2026-09-25:

- [uv lock and sync documentation](https://docs.astral.sh/uv/concepts/projects/sync/)
  distinguishes `--locked` freshness verification from `--frozen` consumption.
  The plan's claim that `--frozen` alone detects metadata drift is incorrect;
  the extra lock check enforces the intended requirement.
- [Hatch build configuration](https://hatch.pypa.io/latest/config/build/) describes
  explicit wheel package selection. The installed C1 distribution's version is
  checked by `tests/test_harness.py`.
- [M00 evidence](../milestones/M00-report.md) records the actual runtime,
  dependency inventory, and clean bootstrap. `uv.lock` records PyPI artifact
  hashes. Downloaded distribution license files were inspected; hashes are in
  `docs/evidence/M00/dependencies.json`.

## Consequences

A contributor needs Git, GNU Make, Bash, uv, and initial network access to public
Python/package sources. No AI credential or backend service is required.
Checkout-local ignored uv cache/runtime directories keep the harness usable in a
restricted workspace. This does not prove future product compatibility, runtime
services, or no-AI operation of later milestones. Revisit Python 3.14 in M02.

## M02 revalidation (2026-09-27)

Keep Python 3.13 for the tested milestone. The installed pySHACL 0.40.1 metadata
and its [official PyPI metadata](https://pypi.org/pypi/pyshacl/0.40.1/json)
state `Requires-Python: >=3.9`, with classifiers through Python 3.13. The M02
planning claim of a 3.13 dependency ceiling was incorrect: classifiers are not
an upper-bound constraint or a Python 3.14 compatibility test. Python 3.14 is
NOT_RUN and remains outside C1's selected runtime; future upgrades require
explicit compatibility checks. Pydantic 2.13.5 is MIT-licensed and declares
Python >=3.9; its installed artifact and transitive licenses are in M02 evidence.
