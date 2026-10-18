"""A plugin module that does I/O when imported (breaks S8)."""

from pathlib import Path

import harnessweaver as hw

Path("noisy-was-here.txt").write_text("imported\n", encoding="ascii")

plugin = hw.Plugin(namespace="noisy", version="0.0.1")
