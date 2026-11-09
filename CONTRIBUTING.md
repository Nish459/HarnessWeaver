# Contributing to HarnessWeaver

Thanks for helping build HarnessWeaver. This guide covers setting up the repository, how a change is made, and what a pull request needs. The engineering rules every change follows are in [RULES.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/RULES.md), the architecture in [DESIGNS.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/DESIGNS.md), and the working notes for AI coding agents (and humans) in [AGENTS.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/AGENTS.md).

## Set up

You need [uv](https://docs.astral.sh/uv/) (Python 3.12 or later; the repository develops on 3.14), and Node 22 or later with [pnpm](https://pnpm.io/) for the TypeScript packages.

```bash
git clone https://github.com/Wise-DreamerZ/HarnessWeaver.git
cd HarnessWeaver
uv sync --all-packages                       # every Python package and the dev tools
pnpm -C typescript install                   # the TypeScript workspace
```

| Task | Command |
| --- | --- |
| Everything CI runs for Python (ASCII check, lint, format check, types, tests, conformance) | `make check` |
| One test | `uv run pytest python/harnessweaver/tests/test_bus.py -q` |
| Coverage (the README badge shows the number CI measures on `main`) | `make cov` |
| Lint and format | `make fmt` |
| Regenerate contract schemas and the OpenAPI document | `make schemas` (`make schemas-check` reports drift) |
| TypeScript tests, types and build | `pnpm -C typescript test`, `pnpm -C typescript typecheck`, `pnpm -C typescript build` |
| The docs site | `make docs` (strict build), `make docs-serve` (browse at http://127.0.0.1:8000) |
| Build, or build and publish, the packages tagged on HEAD | `make build`, `make release` ([Releasing](#releasing)) |
| Remove caches and build output (keeps `.venv` and `node_modules`) | `make clean` (`make distclean` also removes `.venv` and `node_modules`) |

Never `pip install` into the workspace; add dependencies with `uv add --package <member> <dependency>`, and only after an ADR if the dependency is new (RULES C10). The core package takes no new dependencies at all (R6).

## How a change is made

1. **Read the design first.** Find the DESIGNS.md sections your change touches. If the design must change, propose an ADR (a new file in `docs/adr/` and a row in DESIGNS.md No. 28) before writing code.
2. **Discuss larger changes in an issue** before opening a pull request, especially a new module, a contract change or a new dependency.
3. **Write the failing test first** (RULES T1): a unit test, a JSON fixture when the behavior is part of a contract (T4), a property test for merge, outcome or expression logic (T3).
4. **Implement** the simplest thing that works, with the standard library and existing code before anything new. Match the surrounding code.
5. **Run the checks** until they pass: `make check`, plus the TypeScript commands when TypeScript changed (G5).
6. **Update the docs and the changelog** in the same change (D1): the relevant page under `docs/`, and the `CHANGELOG.md` of each package you changed under *Unreleased* (the root one for repository-wide changes).
7. **Open a pull request** with the review checklist below filled in.

## Code conventions

The full list is RULES.md C1 to C12. In short:

- Python 3.12+, fully typed; pyright strict on `core/` and `spec/`. TypeScript in strict mode, ESM only.
- Anything that crosses a boundary is a Pydantic v2 model; spec and config models use `extra="forbid"`, contract values `frozen=True`.
- Async first with anyio; no blocking I/O on the event loop.
- No global mutable state; time comes from the injected clock.
- Only taxonomy errors (`harnessweaver.errors`) cross a public boundary.
- Log with loguru; a package disables its own logs at import. Never log, trace or raise with raw content (R9).
- Every module, class and function has a docstring (Google style); complex logic has comments that explain how and why.
- Only characters from a standard keyboard, in code, docs, fixtures and commit messages (D5): write `No. 13`, `-`, `->` and `...`. `make check` enforces it.

## Tests

- Tests run offline: no network, no API keys, no model spend (R14). Use the test kit: `harness_for_test`, `scripted`, `FakeTool`, `FakeDecider`, cassettes.
- Async tests use `@pytest.mark.anyio`; inject a fake clock instead of sleeping (T8).
- A bug fix starts with a test that reproduces it (T1).
- Behavior defined by a contract gets a language-neutral fixture under `contracts/fixtures/conformance/`, with expected values written by hand from the design, and must pass in Python and TypeScript (R11).
- Every first-party plugin passes the conformance suite (`make conformance`, T5).
- Examples and templates are tests: they run offline in CI, and `init` output must pass its own tests (T6).

## Changing a contract

Hook points, outcomes, actions, the spec format and wire payloads are contracts. Within `harnessweaver/v1`, changes are additive only (V2). Change the contract model first, run `make schemas`, add or extend the fixtures, make Python, TypeScript and the sidecar pass, and update DESIGNS.md, the docs and the changelog. A change that isn't additive needs an ADR and a new major `apiVersion`.

## Docs

- User docs live in `docs/` and build with `make docs`, which fails on a broken link, anchor or a page missing from `mkdocs.yml`'s navigation.
- The website is the landing page in `website/` at `/` and the docs under `/docs/` (ADR-0046). `make docs` writes the docs to `site/docs/` and copies `website/` to `site/`; `make docs-serve` serves the docs alone, with live reload. To see the whole website, run `make site-serve` and open `http://127.0.0.1:8000/`: it builds the site and serves `site/` as Vercel does, with the site's 404 page for a missing path and `/docs` redirected to `/docs/`. The landing page is plain HTML and CSS: edit it directly, and keep its links into the docs relative (`docs/tutorial/`).
- Diagrams are Mermaid, next to the text they explain (D2).
- Code in docs is a tested example or short enough to check by eye; an API that doesn't exist yet is marked *planned* (D3). The tutorial's code lives in `docs_src/` and is run by `docs_src/tests`.
- `QUICKSTART.md`, `CONTRIBUTING.md`, `SECURITY.md` and every `CHANGELOG.md` are included in the site, so links in them are absolute.
- The design guide in `docs/` is the original source document and is never edited; deviations are recorded as ADRs (D4).

## Commits and pull requests

- One logical change per commit, written as a [Conventional Commit](https://www.conventionalcommits.org/) (`feat(core): add hook bus`, `docs: ...`), with a body that says why and cites rules or ADRs (G3).
- Commit only source, docs, lockfiles and the checked-in contract artifacts; never build output, caches, local state or secrets (G4).
- AI-assisted commits carry a `Co-Authored-By:` trailer naming the assistant (G6). An AI agent never commits or pushes without a human's explicit approval for that commit (G1, G2).

Review checklist (also the pull request template):

- [ ] No invariant (R1-R14) is weakened; any rule exception has an ADR.
- [ ] Contract changes start in the models, schemas and fixtures, and pass in Python and TypeScript (R11, T4).
- [ ] New middleware declares `fail_mode`; baseline middleware is `closed` (R2).
- [ ] New guards ship with `mode: log_only` (R8).
- [ ] Nothing raw reaches logs or spans before redaction (R9).
- [ ] No new core dependency (R6); any new dependency has an ADR (C10).
- [ ] Tests are offline, cover the change, and include property tests or fixtures where relevant (T1-T4).
- [ ] Docs and the changed packages' `CHANGELOG.md` files are updated (D1), using only keyboard characters (D5).
- [ ] `make check` is green (G5); the commit is approved by a human (G1).

## Releasing

Every package has its own version (RULES V1), and Git tags say what to release. A release tag is `<package>@<version>`: the package's name on its registry and the version in its `pyproject.toml` or `package.json`, written in SemVer (`1.2.3`, or `1.2.3-rc.1` for a prerelease; build metadata isn't allowed, because npm drops it and PyPI refuses it).

1. Bump the version in the package's manifest, turn *Unreleased* in the package's `CHANGELOG.md` into a section for that version, and merge the change once CI is green.
2. Tag the merged commit, one tag per package: `git tag harnessweaver@0.2.0`, `git tag @harnessweaver/core@0.2.0`.
3. Run `make build`. It checks every tag on HEAD and builds the tagged packages into `dist/release/`, publishing nothing. It stops before building if a tag names no package in the repository, isn't SemVer, or doesn't match its manifest's version.
4. Run `make release`, which does the same from a clean working tree and then publishes: Python packages to PyPI with `uv publish` (a token in `UV_PUBLISH_TOKEN`, or trusted publishing on CI), TypeScript packages to npm with `npm publish` (your npm login; a prerelease goes to the `next` dist-tag, so `latest` stays on the last release).
5. Push the tags: `git push origin harnessweaver@0.2.0 @harnessweaver/core@0.2.0`.

To release one package alone when HEAD has several tags, name it: `make release PACKAGE=harnessweaver-cli`, or `PACKAGE="harnessweaver @harnessweaver/core"` for a few. `make build` takes `PACKAGE` too. A named package still needs its tag on HEAD, and the other tags are left alone.

`make release` publishes `harnessweaver` and `@harnessweaver/core` first. A registry refuses a version it already has, so if a publish fails partway, fix the cause and run `make release PACKAGE="..."` with the packages it hadn't reached.

Tags on commits before the first published release mark where each feature or fix landed in a package. Their manifests still say 0.1.0, so they can't be released: they are history.

A package's first release needs two things the registries can't create from a tag: a PyPI token scoped to your whole account (a project-scoped token needs the project to exist already), and the `harnessweaver` organization on npm, which owns the `@harnessweaver` scope.

### Releasing from CI

Prefer this to `make release`: only a release from the `Release` workflow (`.github/workflows/release.yml`) has the SBOMs and signed attestations that RULES S5 asks for. Push the commit and its tags, then start it, leaving `packages` empty for every tag on the ref:

```bash
gh workflow run release.yml --ref harnessweaver@0.2.0 -f packages="harnessweaver"
```

It runs the checks, builds, attests the artifacts and their SBOMs, then uploads those same files. If an upload fails partway, run it again naming the packages it hadn't reached.

Once the upload is done, its `Smoke test` job installs the packages from PyPI and npm as a user would, each into a fresh environment on Python 3.12 or Node 22, and tries each one offline (`scripts/smoke.py`): the conformance suite for the core and each plugin, a template's project checked and evaluated with the CLI, a running harnessd, and a guarded session in TypeScript. The packages it released are installed at their new version and every other package at its latest, so a new core is tried with the plugins already published; with `packages` set, only those are tried. A registry can take a few minutes to serve a new version, so each install is retried for about five minutes. A failure there means a published package is broken for its users: a registry won't take the same version twice, so fix it in a new release. To try the published packages yourself, run `make smoke`, or `make smoke PACKAGE=harnessweaver-cli` for one.

The setup only the repository's owner can do, once:

1. Make the repository public. GitHub only offers attestations to private repositories on Enterprise Cloud, and npm refuses provenance from a private one.
2. Create a GitHub environment named `release`, with yourself as a required reviewer.
3. On PyPI, give each Python package a trusted publisher: this repository, workflow `release.yml`, environment `release`. PyPI holds only one *pending* publisher (for a project that doesn't exist yet) per repository, workflow and environment, so a release that creates more than one project needs a PyPI API token scoped to your whole account, as the `PYPI_TOKEN` secret of the `release` environment. After that release, add the trusted publisher to each new project (*Manage*, then *Publishing*) and delete the secret.
4. On npm, create the `harnessweaver` organization. A package must exist before npm can trust a publisher for it, so for a first release add a granular access token that can publish, with *Bypass 2FA*, as the `NPM_TOKEN` secret of the `release` environment. Then add a trusted publisher to each package (workflow `release.yml`, environment `release`) and delete the secret. npm plans to take direct publishing away from such tokens in January 2027.

To check a package you downloaded, using the file itself:

```bash
gh attestation verify harnessweaver-0.2.0-py3-none-any.whl --repo Wise-DreamerZ/HarnessWeaver
```

Add `--predicate-type https://cyclonedx.org/bom` to check its SBOM attestation instead. `uv publish` makes no PyPI attestations of its own, so PyPI's page shows none; these are GitHub's, and npm's provenance shows on the npm page.

## Publishing the website

`vercel.json` deploys the website on Vercel from the GitHub repository. It installs uv into a virtual environment of its own (the build image's `python3` is externally managed, PEP 668, so pip can't install into it), builds the site from the `docs` dependency group alone (`uv run --locked --only-group docs mkdocs build --strict`, which also copies the landing page) and serves `site/`, with `/docs` redirected to `/docs/`. Once the Vercel project is connected, every push to `main` updates the production site and every pull request gets a preview deployment.

The setup only the repository's owner can do, once:

1. On Vercel, choose *Add New*, then *Project*, and import this repository. Leave the framework preset at *Other*, the root directory at the repository's root and the build settings empty: `vercel.json` sets them. Choose *Deploy*.
2. To serve it on your own domain, add the domain under the project's *Settings*, then *Domains*, and create the DNS record Vercel shows.

Deploy from Git, not with `vercel deploy` from a working tree: the CLI would upload what Git ignores, such as `.env` files and `site/`. To check a deployment:

```bash
curl -sI https://<deployment>/docs | grep -i -e '^HTTP' -e '^location'
```

It should answer `308` with `location: /docs/`, and `https://<deployment>/` should show the landing page.

## Security issues

Please don't report security vulnerabilities in public issues; see [SECURITY.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/SECURITY.md).

## License

HarnessWeaver is licensed under [Apache-2.0](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/LICENSE). Contributions are made under the same license.
