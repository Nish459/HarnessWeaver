# Tools

A model that can call tools can look things up and change things. That is useful, and dangerous. In HarnessWeaver, **no tool runs without a manifest** (RULES S2), and no call runs without passing the **governor**: deterministic checks on the tool, its arguments, the policy, the data the run has seen, and rate limits, before the tool executes and its result is cleaned up.

This chapter adds a third task, `orders`, that looks orders up with a tool.

## Write the tool

A tool is an ordinary function. Add `helpdesk/tools.py`:

```python title="helpdesk/tools.py"
--8<-- "docs_src/tutorial/tools/helpdesk/tools.py"
```

## Write its manifest

The manifest is the contract between the tool's owner, the security team and the governor: what the model is told, how the tool is reached, what it may touch. Add `tools/lookup_order.tool.yaml`:

```yaml title="tools/lookup_order.tool.yaml"
--8<-- "docs_src/tutorial/tools/tools/lookup_order.tool.yaml"
```

- `transport: native` calls `handler`, a Python function, in the app's process. `http` posts the arguments to a URL, and `code` runs code in a sandbox.
- `description` and `input_schema` are what the model sees. The governor checks every call's arguments against the schema, so `order_id` must look like `A-1234`.
- `side_effect`, `risk`, and later `egress` and `data_access`, describe what a call can do. Policy rules and the governor read them.
- `definition_digest` pins the tool's name, description and schema. More on that below.

!!! tip
    `uv run harnessweaver add tool helpdesk.tools:lookup_order` writes a first manifest from the function's signature and docstring. Review it and fill in what only you know: risk, egress, data access.

## Give the task the tool

Point the spec at the manifests, and add the `orders` task:

```yaml title="harness.yaml (the tools section)"
--8<-- "docs_src/tutorial/tools/harness.yaml:41:42"
```

```yaml title="harness.yaml (the orders task)"
--8<-- "docs_src/tutorial/tools/harness.yaml:66:71"
```

```markdown title="prompts/orders@1.md"
--8<-- "docs_src/tutorial/tools/prompts/orders@1.md"
```

The `direct` runner offers the task's `tools` to the model and runs a **bounded** loop: each call the model asks for is governed and executed, and its result goes back to the model, up to `max_steps` model calls (8 by default). There is no planning and no open-ended agent loop ([ADR-0011](../adr/0011-bounded-tool-loop.md)). `max_tool_calls` in the budget caps the calls too.

## Run it

The offline model asks for the tool first, then answers once it has seen the result:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/tools/harness.offline.yaml"
```

```python title="main.py"
--8<-- "docs_src/tutorial/tools/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
Order A-1002 has shipped; it should reach you in a day or two.
   8 hook    tool.before       harness -> continue
   9 note    tool.before       harness.governor -> continue: allowed
  10 hook    tool.after        harness -> continue
```

The governor's verdict is in the trace (`allowed`). It never records the arguments' values, only the step, the code and the reason (RULES R9).

## The governor

Every tool call passes the same checks, whoever makes it: a runner's tool loop, an agent framework's adapter, or your own `s.tool(...)` in a session.

| Step | Checks | Blocks with |
| --- | --- | --- |
| 1. Registry | The tool has a manifest, is enabled (for this tenant), and its pinned digest matches | `tool_unknown`, `manifest_required`, `tool_disabled`, `digest_mismatch` |
| 2. Schema | The arguments match the manifest's `input_schema` | `schema_invalid` |
| 3. Policy | The policy engine's rules, and what needs a person's approval | `policy_denied` |
| 4. Trifecta | Untrusted content and private data in the run, plus a tool that sends data out | `trifecta` |
| 5. Limits | The manifest's rate limits, per principal and per tenant | `rate_limited` |
| 6. Judge | An optional judge, which may only tighten the decision | `judge_blocked` |
| 7. Approval | A call that needs a person's approval waits for one ([Approvals](approvals.md)) | `approval_rejected` |
| 8. Execute | Runs the tool through its transport, with its timeout | A `ToolError` when the tool fails |
| 9. Output | Sanitizes, truncates to `max_bytes`, and labels the result untrusted | - |

Steps 1 to 7 run on the arguments as the `tool.before` middleware left them, so no middleware can rewrite arguments past the checks ([ADR-0025](../adr/0025-governor-placement.md)). [The tool governor](../advanced/governor.md) explains each step in depth: the lethal trifecta, rate limits, idempotency keys and sandboxed code.

## Pin the definition

A tool whose description or schema changes silently is a classic attack: the model gets new instructions, or the schema accepts new arguments. So a manifest pins its definition with `definition_digest`, a SHA-256 of its name, description and input schema.

`doctor` warns about unpinned manifests, and `tools pin` writes the digests:

```console
$ uv run harnessweaver tools pin harness.yaml
pinned  lookup_order: sha256:13e081247828f80f05a59db148e00a7baeba40e0cb79d28befe87c3fd372c3df
```

From then on, if anyone changes the tool's description or schema without pinning again, the manifest still loads, but **every call to it is blocked** with `digest_mismatch`, until someone reviews the change and runs `tools pin` again ([ADR-0028](../adr/0028-manifests-for-code-tools.md)).

## Calling a tool from your own steps

In a session, `s.tool` calls a tool through the same governor and returns its output:

```python
order = await s.tool("lookup_order", order_id="A-1002")
```

Every manifest field is described in [Tool manifests](../reference/tool-manifests.md).

## Recap

- A **manifest** describes each tool: what the model sees, how it's reached, what it can touch. No manifest, no call.
- The `direct` runner runs a bounded tool loop, and every call passes the nine-step **governor**.
- `definition_digest` pins a tool's definition, and a changed, unpinned tool can't run.
