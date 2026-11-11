# Testing

Your spec is code: rules, guards, budgets and policy that decide what your app does. Test it like code. Everything in HarnessWeaver runs offline against fakes, with no network and no model spend (RULES R14), and the test kit, `harnessweaver.testing`, is what the framework's own tests use.

## Write tests

Add `tests/test_desk.py`:

```python title="tests/test_desk.py"
--8<-- "docs_src/tutorial/testing/tests/test_desk.py"
```

Each test builds a harness from your real `harness.yaml`, with a scripted model in place of the real one, and checks one control:

- **Typed answer.** The model's output comes back as your type.
- **Repair.** A first answer that breaks a rule is repaired once: two model requests, and the rule's outcome is in the trace.
- **No leaks.** The customer's e-mail address appears in neither the model's requests nor the result.
- **Policy.** A $900 refund is blocked with `policy_denied`, before the tool runs.
- **Approval.** A $250 refund waits for finance.

The tests import your `helpdesk` package, so let pytest find it, with a `conftest.py` in the project's root:

```python title="conftest.py"
--8<-- "docs_src/tutorial/testing/conftest.py"
```

(Or set `pythonpath = ["."]` under `[tool.pytest.ini_options]` in `pyproject.toml`.)

## Run them

```console
$ uv run harnessweaver test .
collected 5 items

tests/test_desk.py .....                                                 [100%]

============================== 5 passed in 0.27s ===============================
```

`harnessweaver test` runs pytest in **test mode** (`HARNESSWEAVER_TEST_MODE=1`), where every live provider refuses to call out: model providers, `http` tools, webhook and email approval channels and the OTLP exporter. A test that reaches a real model by accident fails instead of spending money. It also applies the offline overlay. Plain `uv run pytest` works too, if you set test mode yourself.

!!! tip
    Async tests use the anyio pytest plugin: `pytestmark = pytest.mark.anyio`. Time comes from an injected clock, so tests never sleep.

## harness_for_test

```python
harness_for_test(spec, *, model=None, tools=(), deciders=None, clock=None, telemetry=None)
```

| Argument | Meaning |
| --- | --- |
| `spec` | A `harness.yaml` path, a spec document as a dict, or a loaded spec (`hw.load_spec(...)`) |
| `model` | Replaces `models.provider`, usually a `scripted(...)` model |
| `tools` | `FakeTool`s, or any tool backend |
| `deciders` | Fake routing answers, by router name |
| `clock` | A `FakeClock` by default |
| `telemetry` | Where spans and metrics go, for example an in-memory OpenTelemetry SDK |

A dict spec is handy for small tests. `apiVersion`, `kind` and `metadata` may be left out:

```python
harness = harness_for_test(
    {"tasks": {"echo": {"runner": "direct", "output": "str"}}},
    model=scripted("hello"),
)
```

Use `async with harness_for_test(...) as harness:` when the spec has a durable state store, like this one, so the store is closed.

## Scripted models

`scripted(*replies, rules=(), repeat_last=True)` answers from its replies in order, after checking its rules against the last message:

| Helper | Reply |
| --- | --- |
| `text("...")` | A text answer. A plain string works too |
| `output({...})` | Structured output |
| `tool_call("name", **arguments)` | One tool call |
| `reply(**fields)` | Any of `text`, `output`, `tool_calls`, `usage`, `cost_usd`, `model`, `chunks`, `finish_reason`, `fail` |

`model.requests` keeps every request the model got, so a test can check what the model saw.

## Fake tools and deciders

`FakeTool(name, result=None, ...)` is a tool with a manifest built from its fields, so the governor treats it like a real one. Every call is kept in `.calls`, and `raises=` makes it fail. `FakeDecider(choice)` is a routing stage that always gives the same answer: `harness_for_test(..., deciders={"intent": FakeDecider("billing")})`.

## Checking traces

```python
assert_trace(result, "run.start", "input.before", "model.before", "run.end")
assert_trace(result, step("input.before", source="guardrails.input[base-pii]", outcome="continue"))
assert_trace(result, step(kind="note", code="guard_fired"))
assert_trace(result, "run.start", "run.end", exact=True)   # exactly these hooks fired
```

`assert_trace` checks that the expected events appear in that order, with others allowed in between unless `exact=True`. A string is a hook point that fired, and `step(...)` matches any event by its fields. A failure prints the whole trace. `hooks_fired(trace)` lists the hooks that fired, and `render_trace(trace)` prints the trace.

## Checking for leaks

`assert_no_content(where, *values)` fails if any value appears anywhere in a result, a trace, model requests, log lines or span attributes, or any mix of them. It's the test form of RULES R9.

## Recording a real model once

A `Cassette` records a real model's answers once, then replays them offline, matching requests by digest:

```python
model = Cassette("tests/cassettes/triage.json", provider=real_provider, mode="auto")
harness = harness_for_test("harness.yaml", model=model)
```

`replay` never calls out, `record` always does, and `auto` replays when the file exists. `scrub=` cleans each answer before it's saved, so secrets and personal data never reach the file (RULES S7). Record deliberately, outside test mode. In CI, cassettes only replay.

## What to test

| To check | Do |
| --- | --- |
| A guard redacts before the model | Assert the value isn't in `model.requests` (`assert_no_content`) |
| A control blocks | Assert `result.status` and `result.error.details["code"]`, and that the model or tool was never called |
| A repair happens | Script an invalid answer then a valid one; assert two requests |
| A baseline lock holds | Load an overlay that changes a locked path, and expect `LockViolation` from `hw.load_spec` |
| The policy | `harnessweaver policy test` ([Policy](policy.md#test-the-policy)) |
| Quality | Eval suites with baselines ([Evals](evals.md)) |

## Recap

- `harness_for_test` builds your real spec with fakes: `scripted` models, `FakeTool`s, `FakeDecider`s and a fake clock.
- Test mode makes live providers refuse the network, so tests can never spend money.
- `assert_trace` checks what happened, and `assert_no_content` checks what must never leak.
