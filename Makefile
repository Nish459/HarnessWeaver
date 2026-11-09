# Common development tasks. `make check` is what CI runs (RULES G5).
UV ?= uv

.PHONY: sync check ascii lint fmt fmt-check typecheck test conformance cov schemas schemas-check docs docs-serve site-serve build release smoke clean distclean

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

# The website (ADR-0041, ADR-0046). --strict turns every warning, such as a broken link
# or anchor, into an error. The docs are written to site/docs/ and the landing page in
# website/ to site/, which is what Vercel serves; `make docs-serve` serves the docs alone.
docs:
	$(UV) run --group docs mkdocs build --strict

docs-serve:
	$(UV) run --group docs mkdocs serve

# Builds the website and serves site/ as Vercel does, with site/404.html for a missing
# path, at http://127.0.0.1:8000/ (PORT=8001 for another port).
PORT ?= 8000
site-serve: docs
	$(UV) run python scripts/serve_site.py $(PORT)

# Releases (RULES V1): each tag on HEAD, <package>@<version> such as harnessweaver@0.2.0
# or @harnessweaver/core@0.2.0, names one package to release, and its pyproject.toml or
# package.json must have that version. `build` checks the tags and builds the packages
# into dist/release/; `release` builds them and publishes them to PyPI and npm.
# PACKAGE="name ..." releases just those packages (each still needs its tag on HEAD).
PACKAGE ?=
build:
	$(UV) run python scripts/release.py build $(PACKAGE)

release:
	$(UV) run python scripts/release.py publish $(PACKAGE)

# Installs each package from PyPI and npm into a fresh environment, as a user would, and
# tries it offline: at the version its release tag on HEAD names, else the latest. The
# Release workflow runs it after publishing. PACKAGE="name ..." tries just those.
smoke:
	$(UV) run python scripts/smoke.py $(PACKAGE)

# Removes caches and build output: the .gitignore entries for them, anywhere in the
# tree. Installed dependencies (.venv, node_modules), local run state, secrets and
# .claude/ (which holds agent worktrees) are kept.
clean:
	find . \( -name .git -o -name .venv -o -name node_modules -o -name .claude \) -prune -o \
		\( -name __pycache__ -o -name '*.py[cod]' -o -name '*.egg-info' -o -name build -o -name dist \
		-o -name .pytest_cache -o -name .ruff_cache -o -name .pyright -o -name .hypothesis \
		-o -name '.coverage' -o -name '.coverage.*' -o -name htmlcov -o -name '*.tsbuildinfo' -o -name site \) \
		-prune -exec rm -rf {} +

# clean, plus the installed dependencies. Afterwards run `make sync` and
# `pnpm -C typescript install` to work again.
distclean: clean
	find . \( -name .git -o -name .claude \) -prune -o \( -name .venv -o -name node_modules \) -prune -exec rm -rf {} +
