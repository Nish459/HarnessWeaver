"""MkDocs hooks for the docs site (ADR-0042).

The core's docstrings cross-reference with Sphinx roles, such as :class:`Harness` and
:func:`~harnessweaver.core.policy.decide_by_rules`. mkdocstrings renders their Markdown,
where a role is plain text in front of a code span, so the generated API reference
would show ``:class:Harness``. This hook removes the role and, as Sphinx does for a
target that starts with ``~``, keeps only the target's last name.
"""

import re

_ROLE = re.compile(r":(?:attr|class|data|exc|func|meth|mod|obj):<code>(~?)([^<]*)</code>")


def _code_span(match: re.Match[str]) -> str:
    """The role's target as a code span: its last name for a ``~`` target, else all of it."""
    tilde, target = match.groups()
    return f"<code>{target.rsplit('.', 1)[-1] if tilde else target}</code>"


def on_page_content(html: str, **kwargs: object) -> str:
    """Rewrite the Sphinx roles in a page's HTML as plain code spans (an MkDocs hook)."""
    return _ROLE.sub(_code_span, html)
