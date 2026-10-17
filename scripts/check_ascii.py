"""Fail if a repository text file has characters that aren't on a standard keyboard (RULES D5).

Checks every tracked or new, non-ignored file. Write ``No. 13`` instead of a
section sign, ``-`` for dashes, ``->`` for arrows and ``...`` for ellipses.
Unicode test data goes in as escapes (``\\u00e9``).
"""

import subprocess
import sys
import unicodedata
from pathlib import Path

# The design guide is the user's source document and is never edited (RULES D4);
# the lockfile is generated.
EXEMPT = {"docs/AI Harness Framework Design and Build Guide.md", "uv.lock"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".woff", ".woff2"}


def repository_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [name for name in listed.split("\0") if name]


def main() -> int:
    problems: list[str] = []
    for name in repository_files():
        path = Path(name)
        if name in EXEMPT or path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for column, char in enumerate(line, start=1):
                if ord(char) > 127:
                    label = unicodedata.name(char, "unknown")
                    problems.append(f"{name}:{number}:{column}: U+{ord(char):04X} {label}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} non-keyboard character(s); see RULES.md D5", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
