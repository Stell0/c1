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

check: lint typecheck test secrets baseline

clean-start:
	bash scripts/clean_start.sh
