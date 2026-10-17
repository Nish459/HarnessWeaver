# Common development tasks. `make check` is what CI runs (RULES G5).
UV ?= uv

.PHONY: sync check ascii lint fmt fmt-check typecheck test cov schemas schemas-check

sync:
	$(UV) sync --all-packages

check: ascii lint fmt-check typecheck test

ascii:
	$(UV) run python scripts/check_ascii.py

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

# Contract JSON Schemas are generated from the Pydantic models and checked in (ADR-0005).
CONTRACTS_MAIN = import sys; from harnessweaver.contracts import main; sys.exit(main(sys.argv[1:]))

schemas:
	$(UV) run python -c "$(CONTRACTS_MAIN)" contracts/schemas

schemas-check:
	$(UV) run python -c "$(CONTRACTS_MAIN)" --check contracts/schemas
