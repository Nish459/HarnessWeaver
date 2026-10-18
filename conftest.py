"""Repository-wide test settings: every test runs offline (RULES R14, T2)."""

import os

from harnessweaver.ports import TEST_MODE_ENV

os.environ[TEST_MODE_ENV] = "1"
