# Common development tasks. `make check` is what CI runs (RULES G5).
UV ?= uv

.PHONY: sync check ascii lint fmt fmt-check typecheck test conformance cov schemas schemas-check

sync:
	$(UV) sync --all-packages

check: ascii lint fmt-check typecheck test conformance

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

# RULES T5: every first-party plugin passes the conformance suite.
CONFORMANCE_PLUGINS := harnessweaver,openai,anthropic,otel
conformance:
	$(UV) run pytest -q --harnessweaver-conformance=$(CONFORMANCE_PLUGINS) python/harnessweaver/src/harnessweaver/testing/conformance_suite.py

cov:
	$(UV) run coverage run -m pytest -q --harnessweaver-conformance=$(CONFORMANCE_PLUGINS)
	$(UV) run coverage report

# Contract JSON Schemas are generated from the Pydantic models and checked in (ADR-0005).
CONTRACTS_MAIN = import sys; from harnessweaver.contracts import main; sys.exit(main(sys.argv[1:]))

schemas:
	$(UV) run python -c "$(CONTRACTS_MAIN)" contracts/schemas

schemas-check:
	$(UV) run python -c "$(CONTRACTS_MAIN)" --check contracts/schemas
