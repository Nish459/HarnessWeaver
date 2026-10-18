"""The HarnessWeaver test kit: everything to test a harness, a plugin or an app offline.

```python
from harnessweaver.testing import (
    FakeTool, assert_trace, harness_for_test, scripted, text, tool_call,
)

harness = harness_for_test(
    "harness.yaml",
    model=scripted(tool_call("lookup", id="42"), text("Alice is a gold customer.")),
    tools=[FakeTool("lookup", result={"name": "Alice", "tier": "gold"})],
)
result = await harness.run("support", "Who is customer 42?")
assert_trace(result, "run.start", "tool.before", "tool.after", "output.before", "run.end")
```

Nothing here imports pytest; the conformance suite's pytest plugin lives in
``harnessweaver.testing.pytest_plugin`` (RULES T2, T5).
"""

from harnessweaver.modules.models import ScriptedModel, ScriptedReply
from harnessweaver.testing.cassettes import Cassette, request_digest
from harnessweaver.testing.kit import (
    FakeDecider,
    FakeTool,
    FakeTools,
    harness_for_test,
    output,
    reply,
    scripted,
    text,
    tool_call,
)
from harnessweaver.testing.samples import (
    CANARY,
    SAMPLE_TEXTS,
    AdapterSample,
    sample_event,
    sample_request,
)
from harnessweaver.testing.traces import (
    Step,
    assert_no_content,
    assert_trace,
    hooks_fired,
    render_trace,
    step,
)

__all__ = [
    "CANARY",
    "SAMPLE_TEXTS",
    "AdapterSample",
    "Cassette",
    "FakeDecider",
    "FakeTool",
    "FakeTools",
    "ScriptedModel",
    "ScriptedReply",
    "Step",
    "assert_no_content",
    "assert_trace",
    "harness_for_test",
    "hooks_fired",
    "output",
    "render_trace",
    "reply",
    "request_digest",
    "sample_event",
    "sample_request",
    "scripted",
    "step",
    "text",
    "tool_call",
]
