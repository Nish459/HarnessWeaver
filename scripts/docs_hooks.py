"""MkDocs hooks for the docs site (ADR-0042, ADR-0046).

The core's docstrings cross-reference with Sphinx roles, such as :class:`Harness` and
:func:`~harnessweaver.core.policy.decide_by_rules`. mkdocstrings renders their Markdown,
where a role is plain text in front of a code span, so the generated API reference
would show ``:class:Harness``. This hook removes the role and, as Sphinx does for a
target that starts with ``~``, keeps only the target's last name.

The docs are built into ``site/docs/``, and the landing page in ``website/`` is copied
to ``site/``, the website's root, once they are built.
"""

import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ROLE = re.compile(r":(?:attr|class|data|exc|func|meth|mod|obj):<code>(~?)([^<]*)</code>")


def _code_span(match: re.Match[str]) -> str:
    """The role's target as a code span: its last name for a ``~`` target, else all of it."""
    tilde, target = match.groups()
    return f"<code>{target.rsplit('.', 1)[-1] if tilde else target}</code>"


def on_page_content(html: str, **kwargs: object) -> str:
    """Rewrite the Sphinx roles in a page's HTML as plain code spans (an MkDocs hook)."""
    return _ROLE.sub(_code_span, html)


def on_post_build(config: Mapping[str, Any], **kwargs: object) -> None:
    """Copy the landing page to the folder that holds the docs (an MkDocs hook, ADR-0046).

    ``mkdocs.yml`` builds the docs into ``site/docs/``, so ``site/`` is the website's
    root and gets the files in ``website/``. ``mkdocs serve`` builds into a temporary
    folder that isn't named ``docs`` and serves the docs alone, so it copies nothing.
    """
    site_dir = Path(config["site_dir"])
    if site_dir.name == "docs":
        website = Path(config["config_file_path"]).parent / "website"
        shutil.copytree(website, site_dir.parent, dirs_exist_ok=True)
