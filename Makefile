# Common development tasks. `make check` is what CI runs (RULES G5).
UV ?= uv

.PHONY: sync check lint fmt fmt-check typecheck test cov

sync:
	$(UV) sync --all-packages

check: lint fmt-check typecheck test

lint:
	$(UV) run ruff check .

fmt:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

fmt-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run pyright

test:
	$(UV) run pytest -q

cov:
	$(UV) run coverage run -m pytest -q
	$(UV) run coverage report
