# M14c reproducible qualification

The [milestone report](../../milestones/M14c-report.md) is authoritative for gate
status and released artifacts. Expected case lists are captured before execution;
JUnit results must match them exactly, with no failed or skipped mandatory cases.
Raw logs, tokens, snapshots and credentials stay in private temporary directories.

## Pinned fixtures

Use Python 3.13 and `uv.lock`, Docker, Docker Compose 2.39.4, and the committed
image digests in `deployment/images.json`, `deployment/reference/images.json`
and `deployment/external-test/compose.yaml`. Hydra 2.3.0 is independently managed
by the supervisor fixture; its [Apache-2.0 license](licenses/hydra-LICENSE) is
pinned to tagged source. Its login/consent service is synthetic; discovery,
S256, signatures, JWTs, refresh and logout are implemented by the real provider.

Run `make bootstrap` and install locked Chromium with:

```sh
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" uv run --locked playwright install chromium
```

Prepare a private `/tmp/c1-m14c-dev/` directory and start the disposable `c1-dev`
stack with `C1_PROBE_ENV_FILE=/tmp/c1-m14c-dev/.env`, `C1_CONTAINER_RUNTIME=docker`,
`COMPOSE=/tmp/c1-m14c-tools/docker-compose`, development ports 17363/19080/19090,
matching `C1_PROBE_*_URL` settings, and `C1_FGA_DEADLINE=30s`. Use `make stack-up`;
the existing launcher generates private synthetic credentials. Do not reuse a
production stack or overwrite another deployment's environment file.

Start `deployment/external-test/compose.yaml` as project `c1-m14c-external`.
Supply the fixture-only `C1_EXTERNAL_*` values specified in
`tests/integration/m14c/conftest.py` and the recovery fixture. The compose file
pins all services; C1 itself never starts them or registers the OIDC client.
The supervisor fixture alone can call Hydra's administrative port 29091.

Prepare `/tmp/c1-m14c-reference/` with the reference compose, nginx template and
PostgreSQL initialization script. The reference harness **recreates this test
project**, its certificates, credentials and volumes, and separately exercises
`c1-dr`. These project names must contain no unrelated deployment data.

## Execute and retain results

Build the candidate image with its source revision:

```sh
docker build -f deployment/reference/Containerfile \
  --build-arg C1_REVISION="$(git rev-parse HEAD)" -t localhost/c1:0.1.0rc2 .
bash docs/evidence/M14c/run-gate.sh check
bash docs/evidence/M14c/run-gate.sh external
bash docs/evidence/M14c/run-gate.sh regression
bash docs/evidence/M14c/run-gate.sh reference
PYTHONPATH="$PWD" PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" \
  uv run --locked python docs/evidence/M14c/release-image-workflow.py
```

The runner clears AI credential variables and uses 30-second backend deadlines.
External and regression suites share the legacy development services, so a
process lock serializes them. Reference fixtures are isolated and never use
`C1_REFERENCE_REUSE`. Store stdout/stderr, exit codes and JUnit under a private
`C1_GATE_OUTPUT` directory (default `/tmp/c1-m14c-final`). Publish only sanitized
evidence, the exact source/image pins, dependency/provider versions, expected
case comparison and PASS/FAIL/NOT_RUN outcomes.

The image workflow runs initialization and enrollment/browser/API checks inside
the built image with a read-only root filesystem. Set `C1_RELEASE_IMAGE` to the
immutable image ID being qualified. The supervisor fixture alone registers its
client and manages its synthetic login UI. Run it separately from other external
browser cases that use ports 29092/29095.

For a corrected test-fixture failure, the regression runner accepts explicit test
paths after `regression`. Retain the original failed attempt and the corrected
rerun separately. Qualification requires the combined successful cases to match
the complete expected list exactly; never count a failed setup as a passed case.

Dedicated application persistence is required by the qualified full-storage
backup transport. An external IdP database or signing key is never a C1 backup
artifact. The production/recovery qualification is distinct from implementing
an interface or passing an individual development test.

## Published artifact

The final [release pins](artifact-pins.json) identify the downloadable amd64 archive,
wheel and source package. Buildx 0.38.0 exports a complete Docker archive directly;
the report records the exact command, binary checksum, imported-image workflow and
audit. The first classic Docker export omitted layer blobs and was rejected.
Verify `SHA256SUMS` and use the imported immutable image ID. Tagged source captures
the candidate before publication; the report on main records final Gate B closure
without moving the tag or replacing any artifact.
