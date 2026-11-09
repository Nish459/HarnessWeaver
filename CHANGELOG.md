# Changelog

Each package keeps its own changelog, with a section for every version:

| Package | Changelog | First published version |
| --- | --- | --- |
| `harnessweaver` | [python/harnessweaver](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/harnessweaver/CHANGELOG.md) | 0.18.0 |
| `harnessweaver-cli` | [python/harnessweaver-cli](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/harnessweaver-cli/CHANGELOG.md) | 0.7.1 |
| `harnessweaver-sidecar` | [python/harnessweaver-sidecar](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/harnessweaver-sidecar/CHANGELOG.md) | 0.2.1 |
| `harnessweaver-openai` | [python/plugins/openai](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/openai/CHANGELOG.md) | 0.2.0 |
| `harnessweaver-anthropic` | [python/plugins/anthropic](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/anthropic/CHANGELOG.md) | 0.2.0 |
| `harnessweaver-otel` | [python/plugins/otel](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/otel/CHANGELOG.md) | 0.2.1 |
| `harnessweaver-pydantic-ai` | [python/plugins/pydantic-ai](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/pydantic-ai/CHANGELOG.md) | 0.1.2 |
| `harnessweaver-monty` | [python/plugins/monty](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/monty/CHANGELOG.md) | 0.2.1 |
| `harnessweaver-cel` | [python/plugins/cel](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/python/plugins/cel/CHANGELOG.md) | 0.1.1 |
| `@harnessweaver/core` | [typescript/packages/core](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/typescript/packages/core/CHANGELOG.md) | 0.5.0 |
| `@harnessweaver/ai-sdk` | [typescript/packages/ai-sdk](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/typescript/packages/ai-sdk/CHANGELOG.md) | 0.2.0 |

Below are the changes that belong to the repository rather than to one package: the examples, the docs site, CI and the release tooling. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A *Spec generator* page in the docs (`docs/learn/spec-generator.md`, under Learn) that writes, from choices in a form and as they are made, every document a project is made of: an app spec (`kind: Harness`) for a task, a session with no task or a wrapped client or agent, in Python or TypeScript, with its model, task, budget, guards (in harnessd too), retrieval, routing, memory, rules, approvals, state, telemetry, plugins and middleware; a profile (`kind: Profile`), as an org baseline, a team's or a plugin's, with its locks, bounds and required level; an environment overlay (`kind: Overlay`); a tool manifest (`kind: Tool`); and an eval suite. Each comes with the files it refers to and the commands that install, check and use it. Everything runs in the browser. Guards added there start in shadow mode (RULES R8). The writers are `docs/javascripts/spec-generator.js` and the page's wiring `spec-generator-page.js`; `docs_src/tests/test_spec_generator.py` runs the writers with Node.js on sets of choices and loads each document as the page says to: `spec validate` for app specs and overlays, an app under each profile (and its locks and bounds must hold), an app that uses each tool after `tools pin` and `doctor`, and `eval run` for each suite. A plugin's profile is loaded from an installed plugin package, and the TypeScript app specs are loaded and run in a session by the TypeScript core, in the TypeScript CI job, which builds it. The landing page, the Learn page, the section reference, *Write an org baseline* and *Tool manifests* link to it.
- Smoke tests for every package, run by the `Release` workflow once it has published (`scripts/smoke.py`, a new `smoke` job). Each package is installed from PyPI or npm into a fresh environment of its own, on Python 3.12 or Node 22, and tried offline: the conformance suite for the core and each plugin, a template's project checked and evaluated with the CLI, a running harnessd, and a guarded session in TypeScript. The released packages are installed at their new version and the rest at their latest, so a new core is also tried with the plugins already published, and an install is retried while a registry catches up. `make smoke` runs it locally, and `scripts/tests/test_smoke.py` runs the Python checks against the workspace offline.
- A recipe, *Serve it from a web app* (`docs/how-to/web-app.md`): the tutorial's support desk behind FastAPI, with the harness loaded once in the app's lifespan, each run acting for its caller, idempotency keys made per caller, run statuses mapped to HTTP statuses, approvals over HTTP, and answers streamed as server-sent events. Its app is `docs_src/web_app/app.py`, which `docs_src/tests/test_web_app.py` runs.
- The docs show how to call a real model without a gateway: OpenAI, Claude or a local Ollama model directly, besides LiteLLM Proxy (the Quickstart's last step, and *First steps* in the tutorial). Troubleshooting has a section on failed runs (a missing key, nothing listening at `base_url`, a refused key, an unknown model, rate limits) and covers a CLI that isn't on the `PATH` and a default Python older than 3.12.
- The Learn page lays out the path from zero to production, and the docs home links the Quickstart and says how to start a project.
- `README.md` shows badges for CI, coverage, the PyPI and npm versions, the supported Python and Node versions, the license and the docs. A `Coverage` job in CI runs `make cov` on each push to `main`, after the Python jobs pass, and writes the total to `coverage.json` on the `badges` branch, which the coverage badge reads.
- The website has a landing page at `/`, and the docs move under `/docs/` (ADR-0046). The page is plain HTML and CSS in `website/`; `make docs` builds the docs into `site/docs/` and copies the landing page to `site/`, which Vercel serves. The docs header's logo leads to the landing page, Vercel redirects `/docs` to `/docs/` and serves the landing page's `404.html` for a missing path, and a test checks the landing page's links into the docs. `make site-serve` builds the website and serves it as Vercel does, with the 404 page for a missing path (`scripts/serve_site.py`). `CONTRIBUTING.md` explains how to preview and publish the website.
- The docs compare `openai.chat` and `anthropic.messages`: what Claude loses through Chat Completions, and that `instrument()` follows the client, not `models.provider` (`docs/reference/providers.md`).
- The `Release` workflow (`.github/workflows/release.yml`) runs the checks, builds the tagged packages, attests their provenance and SBOMs (RULES S5) and publishes those same files with trusted publishing. A release that creates more than one PyPI project, which PyPI's pending publishers can't do, uploads with an account-wide token from the `PYPI_TOKEN` secret instead, and a package's first npm release with one from `NPM_TOKEN`. `scripts/release.py upload` uploads an earlier build unchanged. The `@harnessweaver` packages name their repository, which npm's provenance requires.

### Changed

- The Quickstart needs no clone: `uvx --from harnessweaver-cli harnessweaver init` creates the project, `uv sync` installs it from PyPI, and every step runs inside it with `uv run`, ending with a real model. The examples, which do need a clone, moved to its end. `README.md`'s *Try it* follows the same path.
- `README.md`, `QUICKSTART.md` and the packages' READMEs link to the docs site rather than to GitHub's view of `docs/`, which doesn't show the code the pages include, and the packages' READMEs use absolute links, which work on PyPI.
- `make release` publishes TypeScript packages with `npm publish` instead of `pnpm publish`, because pnpm only warns when trusted publishing fails. It needs an npm login, not a pnpm one.

### Fixed

- The Vercel build installs uv 0.13.6 into a virtual environment of its own. The build image's `python3` is now managed by uv and marked externally managed (PEP 668), so `pip install` into it failed and no deployment could build.

## 2026-11-01

### Added

- Each package has its own `CHANGELOG.md`, with a section per version, and a test requires a section for its current version. This file now holds only repository-wide changes, and the docs site's Release Notes has a page per package.

### Security

- Dependencies with known advisories are updated: certifi 2026.10.23 (GHSA-6q48-6c7w-9gw2, a bundled root CA whose intermediates have compromised keys), uv 0.13.6 in the harnessd image and the Vercel docs build (GHSA-hq85-5cpj-mr62, the same root in uv's CA store), and zod 4.6.7 in the development dependencies of `@harnessweaver/ai-sdk` and Example 04 (GHSA-mrhx-c7xc-m3w5, memory exhaustion on oversized arrays).

### Fixed

- `make release` publishes `harnessweaver` and `@harnessweaver/core` first, so a failure partway never leaves a published package whose core isn't there. It also no longer refuses to run because of `.claude/`, which is now ignored.

## 2026-10-26

### Added

- `vercel.json` deploys the docs site on Vercel from the GitHub repository, built from the `docs` dependency group alone, which now includes ruff so that mkdocstrings formats signatures as `make docs` does.

## 2026-10-25

### Added

- The docs site (ADR-0041, ADR-0042): `mkdocs.yml` and `docs/`, built with MkDocs and Material by `make docs` (strict: broken links and anchors fail) and served by `make docs-serve`, with its tools in a `docs` dependency group and a CI job. It follows the structure of FastAPI's documentation, with top-level tabs for Home, Features, Learn, Reference, Resources, About and Release Notes:
  - **Home** shows a first example and an upgraded one, the requirements, the dependencies and the license; **Features** lists what the framework does.
  - **Learn** holds the quickstart and the concepts (lifecycle and hook points, the hook bus, outcomes and errors, the envelope and budgets, the spec, integration styles, adoption levels), a nineteen-chapter **Tutorial - User Guide** that builds one support-desk app from first steps through models, prompts, typed output, repairs, budgets, guardrails, profiles and the org baseline, sessions, routing, retrieval, tools, policy, approvals, state and replay, observability, testing, evals and debugging, each ending with a Recap, an **Advanced User Guide** (layers, locks and bounds; the tool governor; approvals in depth; TypeScript; harnessd; plugins, providers, middleware, runners and adapters, conformance), the CLI reference, **Deployment** (installation, versions, configuration, gateways and the dev stack, security) and **How To - Recipes** (governing an existing client, writing an org baseline, troubleshooting).
  - **Reference** holds the spec's section reference, every provider's settings, the built-in profiles, tool manifests, cel-lite, the modules, the contracts, and a Python API reference generated from the docstrings with mkdocstrings (a new docs-only dependency).
  - **Resources** (getting help, the examples, project templates, contributing, the security policy) and **About** (alternatives and comparisons, history, design and future, the ADRs).
  - The tutorial's code lives in `docs_src/tutorial/`, one folder per chapter, and `docs_src/tests` runs every chapter offline and checks it prints what its page shows.
  - `console` blocks play as typed terminal sessions (termynal, vendored with its MIT license), and the footer links to GitHub.
  - Its theme (`docs/stylesheets/brand.css`) has the HarnessWeaver logo (an H woven from two threaded strands, `docs/assets/logo.svg`) and a favicon rendered from it, the Inter font, a dark navy palette by default and a light one behind the toggle.
- `QUICKSTART.md` (an offline walk from a clone to a governed, traced and tested task of your own, checked from a fresh clone), `CONTRIBUTING.md` and `SECURITY.md`; READMEs for `@harnessweaver/core` and `@harnessweaver/ai-sdk`.
- `make build` and `make release` build, and publish to PyPI and npm, the packages that the Git tags on HEAD name (`scripts/release.py`). A release tag is `<package>@<version>`, and its SemVer version must equal the package's manifest version (RULES V1). `PACKAGE=<name>` releases just the named packages.
- `make clean` removes caches and build output (`__pycache__`, the pytest, ruff, pyright and Hypothesis caches, coverage data, `build/`, `dist/`, `*.egg-info`, `*.tsbuildinfo` and the docs `site/`), keeping `.venv`, `node_modules`, local run state and `.claude/`. `make distclean` also removes `.venv` and `node_modules`.

### Changed

- Each ADR now has its own file under `docs/adr/`, carried over word for word, and DESIGNS.md No. 28 indexes them; ADR-0041 records the docs toolchain.

### Fixed

- AGENTS.md named a test that doesn't exist, and gave a plugin-conformance command that, at the repository root, runs the normal tests and no conformance checks (the suite file sits inside the `python` test path); it now names the suite file, as `make conformance` does. The plugin READMEs say to run their command from the package's directory.
- DESIGNS.md's example spec set `observability.exporter: otlp` without `configure_sdk: true`, which fails loading; its YAML now parses and loads as written. The `anthropic.messages` settings tables now show the provider's own `timeout` (600s), `max_retries` (2) and `cost_header` defaults.
- The README's and the docs home page's first example is now Example 01's real spec and code, runnable as written, instead of a fragment with undefined names.

## 2026-10-23

### Added

- CI runs the TypeScript workspace (types, tests, build) on Node 22 and 24, with SHA-pinned actions.
- Example 04 (`examples/04_polyglot_typescript`): Example 02's spec from TypeScript, in process with the Vercel AI SDK and through harnessd. Its tests pass Example 02's golden set with the TypeScript graders, require the same answers from the app and from harnessd, and run the README's `curl` walkthrough as written. The example is part of the pnpm workspace, and the CI TypeScript job installs the Python workspace to start harnessd.

## 2026-10-20

### Added

- Example 02, `examples/02_support_rag`: a customer-facing support assistant in the Session style with routing, ACL-checked context, injection guards on questions and retrieved articles, citations, a `run.start` policy, and tests that Acme's baseline locks hold.
- Example 03, `examples/03_refund_agent`: a refund agent in the Run style (the `pydantic_ai.agent` runner) and the Wrap style (`harness.wrap` on an existing agent), with governed tools, policy rules, the lethal-trifecta check, finance approvals, Acme's own middleware and guard as a local plugin, `policy_tests.yaml`, and a red-team eval set that passes offline.
- `deploy/harnessd/Dockerfile`: harnessd built from `uv.lock` on digest-pinned bases (S5), running as an unprivileged user.
- Examples 02 and 03 keep the configs `harnessweaver gateway` generates under `gateway/`, tested as golden files.

### Changed

- `examples/_org/acme-baseline.yaml` 1.1.0 also allows the `pydantic_ai` and `acme` plugins (a loosening, so a minor version, V3).
- Example 01's offline overlay answers every golden case, so `harnessweaver eval run -e offline` passes on it, and it tests its golden set.

## 2026-10-18

### Added

- Example 01, `examples/01_invoice_extraction`: typed invoice extraction at L1 in the Run style, with PII redaction, a secrets check, business rules, a repaired answer, budgets and prices, and `l0_instrument.py`, which governs an existing OpenAI client in three lines. It runs offline and its tests run in CI, with no app-level retry or tracing code.
- `examples/_org/acme-baseline.yaml`: an org baseline profile (v1) with a locked plugin allow-list, locked guards and content capture, budget bounds and a required level per risk tier, with tests that each lock and bound fails loading.
- `make conformance` runs the conformance suite on every first-party plugin and is part of `make check`.

## 2026-10-17

### Added

- uv workspace with the core package `harnessweaver`, the developer tooling `harnessweaver-cli` (the `harnessweaver` command), the sidecar `harnessweaver-sidecar` (`harnessd`), and the first-party plugin packages `harnessweaver-openai`, `harnessweaver-anthropic`, `harnessweaver-pydantic-ai`, `harnessweaver-monty`, `harnessweaver-otel` and `harnessweaver-cel`.
- `make check` (ruff, ruff format, pyright, pytest), CI on Python 3.12-3.14 with SHA-pinned actions, pre-commit hooks and a pull request template.
- `make check` also rejects characters that aren't on a standard keyboard (`scripts/check_ascii.py`, RULES D5).
