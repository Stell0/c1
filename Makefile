UV ?= uv
# Keep all generated tools/cache inside the checkout unless explicitly overridden.
export UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
export UV_PYTHON_INSTALL_DIR ?= $(CURDIR)/.uv-python
export UV_PYTHON_BIN_DIR ?= $(CURDIR)/.uv-python/bin

.PHONY: bootstrap lint typecheck test secrets baseline check clean-start

bootstrap:
	$(UV) python install 3.13
	$(UV) lock --check
	$(UV) sync --frozen

lint:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

typecheck:
	$(UV) run --locked mypy

test:
	$(UV) run --locked pytest

secrets:
	$(UV) run --locked python scripts/check_secrets.py

baseline:
	$(UV) run --locked python scripts/check_baseline.py

check: lint typecheck test secrets baseline profile

clean-start:
	bash scripts/clean_start.sh

export COMPOSE ?= podman compose
.PHONY: stack-up stack-down stack-reset probe inventory
stack-up:
	$(UV) run --locked python -m scripts.stack up
stack-down:
	$(UV) run --locked python -m scripts.stack down
stack-reset:
	$(UV) run --locked python -m scripts.stack reset
probe:
	@test "$$C1_STACK" = 1 || (echo "Set C1_STACK=1 to run the real-service gate"; exit 1)
	$(UV) run --locked pytest -s -m integration tests/integration/m01 -p no:cacheprovider --junitxml docs/evidence/M01/junit.xml
inventory:
	$(UV) run --locked python -m scripts.inventory

.PHONY: integration profile
integration:
	@test "$$C1_STACK" = 1 || (echo "Set C1_STACK=1 to run real-service integration"; exit 1)
	@mkdir -p docs/evidence/M03
	$(UV) run --locked pytest -s -m integration tests/integration -p no:cacheprovider --junitxml docs/evidence/M03/junit.xml
profile:
	$(UV) run --locked python scripts/build_profile.py --check
	$(UV) run --locked python scripts/build_software_profile.py --check

.PHONY: api-up api-down
api-up:
	$(UV) run --locked python -m scripts.api up $(if $(C1_CRASH_AFTER),--crash-after $(C1_CRASH_AFTER),)
api-down:
	$(UV) run --locked python -m scripts.api down
