# Common development tasks. `make check` is what CI runs (RULES G5).
UV ?= uv

.PHONY: sync check ascii lint fmt fmt-check typecheck test conformance cov schemas schemas-check docs docs-serve

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
CONFORMANCE_PLUGINS := harnessweaver,openai,anthropic,otel,cel,monty,pydantic_ai
conformance:
	$(UV) run pytest -q --harnessweaver-conformance=$(CONFORMANCE_PLUGINS) python/harnessweaver/src/harnessweaver/testing/conformance_suite.py

cov:
	$(UV) run coverage run -m pytest -q --harnessweaver-conformance=$(CONFORMANCE_PLUGINS)
	$(UV) run coverage report

# Contract JSON Schemas are generated from the Pydantic models and checked in (ADR-0005),
# and so is harnessd's OpenAPI document (ADR-0038).
CONTRACTS_MAIN = import sys; from harnessweaver.contracts import main; sys.exit(main(sys.argv[1:]))

schemas:
	$(UV) run python -c "$(CONTRACTS_MAIN)" contracts/schemas
	$(UV) run python -m harnessweaver_sidecar.openapi contracts/openapi

schemas-check:
	$(UV) run python -c "$(CONTRACTS_MAIN)" --check contracts/schemas
	$(UV) run python -m harnessweaver_sidecar.openapi --check contracts/openapi

# The docs site (ADR-0041). --strict turns every warning, such as a broken link or
# anchor, into an error; the site is written to site/.
docs:
	$(UV) run --group docs mkdocs build --strict

docs-serve:
	$(UV) run --group docs mkdocs serve
