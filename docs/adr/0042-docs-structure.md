# ADR-0042: The docs' structure, with tested tutorial code

**Status:** Accepted. Amended by [ADR-0047](0047-docs-for-users.md).

## Decision

The docs site keeps MkDocs and Material ([ADR-0041](0041-docs-site.md)) and has this structure:

- **Top-level tabs:** Home, Features, Learn, Reference, Resources, About and Release Notes. Learn holds the concepts, a step-by-step **Tutorial - User Guide**, an **Advanced User Guide**, the CLI, **Deployment** and **How To - Recipes**.
- **One running example.** The tutorial builds one app, a support desk, chapter by chapter. Each chapter ends with a Recap. The code each chapter shows lives in `docs_src/tutorial/`: a folder per chapter holds the project as it stands at the end of that chapter (its specs, prompts, manifests and datasets), and the shared Python package `helpdesk` holds its code. The pages include these files with `pymdownx.snippets`, and `docs_src/tests/` runs each chapter offline, so the code in the tutorial is tested code (RULES D3, T6).
- **A generated Python API reference.** The Reference tab documents the public API from its docstrings with [mkdocstrings](https://mkdocstrings.github.io/) and its Python handler (`mkdocstrings[python]`), added to the workspace's `docs` dependency group. The handler reads the source statically (Griffe), so building the docs imports no HarnessWeaver code.
- **Animated terminal sessions.** `console` code blocks are played as a typed terminal session by [termynal](https://github.com/ines/termynal) (MIT, by Ines Montani), vendored into `docs/javascripts/termynal.js` and `docs/stylesheets/termynal.css` with its license notice. Its non-keyboard characters are written as escapes (RULES D5). A small script of our own, `docs/javascripts/terminals.js`, turns each block into a terminal. Without JavaScript, the block stays an ordinary code block.
- The core's docstrings cross-reference with Sphinx roles (`` :class:`Harness` ``), which mkdocstrings prints as text. A ten-line MkDocs hook, `scripts/docs_hooks.py`, shows them as code spans in the rendered pages, so the docstrings stay as they are.
- The footer links to the project on GitHub (`extra.social`).

## Why

A reader learns by building one app in small steps, finds every detail in a reference, and finds the background, deployment and project pages in predictable places. A tutorial whose code is run by the test suite can't drift from the framework, which hand-written snippets do.

mkdocstrings is the standard way to document a Python API from its docstrings in MkDocs. Every module already has Google-style docstrings (RULES C9), so the reference costs no extra writing and can't drift from the code. It lives in the `docs` dependency group, like Material, so no published package depends on it (R6, C10).

termynal is a single small script and stylesheet with no dependencies of its own. Vendoring it avoids a JavaScript build step for the docs. Loading it from a CDN would make the site depend on a third party at runtime.
