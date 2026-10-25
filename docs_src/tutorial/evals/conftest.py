"""Make the helpdesk package importable in tests, as it is when the app runs."""

import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
