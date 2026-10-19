"""Harness: the runtime object an app builds from its spec (DESIGNS No. 6, No. 7, No. 18).

```python
harness = hw.Harness.load("harness.yaml")
result = await harness.run("extract_invoice", doc, principal="alice")
```

Loading resolves every name the spec references through the plugin registry,
installs the spec's middleware on the hook bus, builds each task's runner and
checks that the runner reaches every hook the baseline needs (R4). Anything
wrong fails here, at load, never at run time.
"""

from harnessweaver.harness.harness import Harness
from harnessweaver.harness.records import PendingSession

__all__ = ["Harness", "PendingSession"]
