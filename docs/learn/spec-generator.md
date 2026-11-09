---
hide:
  - toc
---

# Spec generator

Pick what your app needs, and this page writes its `harness.yaml` as you go. It runs in your browser: nothing you type leaves the page. Copy or download the spec, create the files it lists, and check it with `harnessweaver spec validate`.

<div class="hw-gen">
<form id="hw-gen-form" class="hw-gen__form" autocomplete="off">
<fieldset>
<legend>The app</legend>
<label>Name<input name="name" value="support-desk" required pattern="[a-z0-9][a-z0-9._\-]*"><small>Lowercase letters, digits, <code>.</code>, <code>_</code> and <code>-</code>.</small></label>
<label>Owner<input name="owner" value="support-team"><small>The team that owns it.</small></label>
<label>Risk tier<select name="risk_tier"><option value="internal">internal</option><option value="customer_facing">customer_facing</option><option value="takes_actions">takes_actions</option></select><small>Your org baseline picks the adoption level an app must reach by its tier.</small></label>
</fieldset>
<fieldset>
<legend>Starting point</legend>
<label>Profile<select name="profile"><option value="extraction">extraction: typed output from text</option><option value="rag">rag: answers from documents</option><option value="agent">agent: a model that calls tools</option><option value="workflow">workflow: a fixed pipeline of steps</option><option value="chat">chat: streamed conversation</option><option value="none">none: only the framework's defaults</option></select><small>The guards and the deadline the profile adds are listed below the form.</small></label>
<label>Org baseline<input name="baseline" placeholder="org://acme-baseline@^1"><small>Optional: your platform team's profile, which every app extends.</small></label>
</fieldset>
<fieldset>
<legend>Model</legend>
<label>Provider<select name="provider"><option value="openai.chat">openai.chat: any OpenAI-compatible endpoint, such as LiteLLM</option><option value="anthropic.messages">anthropic.messages: Claude, through the Messages API</option><option value="scripted">scripted: canned answers, offline</option></select></label>
<div data-when="provider=openai.chat">
<label>Endpoint<input name="base_url" value="http://localhost:4000"><small>Usually your gateway, which holds the provider keys.</small></label>
<label>API key variable<input name="api_key_env" value="LITELLM_API_KEY"><small>The environment variable with the key. Keys never go in the spec.</small></label>
</div>
<div data-when="provider=anthropic.messages">
<label>Effort<select name="effort"><option value="">the model's default</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option></select></label>
</div>
<div data-when="provider=openai.chat|anthropic.messages">
<label>Model for the <code>fast</code> alias<input name="fast_model" value="your-fast-model"><small>The default alias. Your code and tasks name aliases, never models.</small></label>
<label>Model for the <code>strong</code> alias<input name="strong_model" placeholder="optional"></label>
</div>
<div data-when="provider=scripted">
<label>Reply<input name="reply" value="Hello."><small>What the scripted model answers, for trying the spec with no network and no keys.</small></label>
</div>
</fieldset>
<fieldset>
<legend>The task</legend>
<label>Name<input name="task" value="support"></label>
<label>Runner<select name="runner"><option value="direct">direct: the harness calls the model, with a bounded tool loop</option><option value="session">session: your own async function</option><option value="workflow">workflow: your steps, in order</option><option value="pydantic_ai.agent">pydantic_ai.agent: a Pydantic AI agent</option></select></label>
<div data-when="runner=session">
<label>Handler<input name="handler" value="app.flow:answer"><small><code>package.module:function</code>, called as <code>await answer(session, input)</code>.</small></label>
</div>
<div data-when="runner=workflow">
<label>Steps<input name="steps" value="app.steps:clean, app.steps:classify, app.steps:reply"><small>Functions, comma-separated; each step runs after the one before it.</small></label>
</div>
<div data-when="runner=pydantic_ai.agent">
<label>Agent<input name="agent" value="app.agent:support_agent"><small><code>package.module:attribute</code> of a Pydantic AI agent.</small></label>
</div>
<div data-when="runner=direct|pydantic_ai.agent">
<label>Prompt<input name="prompt" value="support@1"><small>A versioned prompt, <code>name@version</code>, in <code>prompts/</code>. Empty for none.</small></label>
<label>Tools<input name="tools" placeholder="lookup_order, refund_payment"><small>Tool names, comma-separated. Each needs a manifest.</small></label>
</div>
<label>Input type<input name="input" placeholder="app.models:Ticket"><small>Optional: the Pydantic model the input is checked against.</small></label>
<label>Output type<input name="output" value="str"><small><code>str</code> for text, or a Pydantic model such as <code>app.models:Triage</code>.</small></label>
<div class="hw-gen__row">
<label>Model calls<input name="max_model_calls" type="number" min="0" value="3"></label>
<label>Tool calls<input name="max_tool_calls" type="number" min="0"></label>
<label>Cost, USD<input name="max_usd" type="number" min="0" step="0.01" value="0.05"></label>
<label>Deadline<input name="deadline" placeholder="30s"></label>
</div>
<small>The budget for each run of the task. Empty fields set no limit.</small>
<label class="hw-gen__check"><input name="evals" type="checkbox" checked> Add a golden eval set</label>
</fieldset>
<fieldset>
<legend>Guardrails</legend>
<small>On top of the profile's own guards.</small>
<label class="hw-gen__check"><input name="guard_pii" type="checkbox"> Redact PII in the input</label>
<label class="hw-gen__check"><input name="guard_injection" type="checkbox"> Block prompt injection in the input</label>
<label class="hw-gen__check"><input name="guard_topics" type="checkbox"> Block input about denied topics</label>
<div data-when="guard_topics=on">
<label>Denied words<input name="topics" placeholder="lawsuit, diagnosis, prescription"><small>Comma-separated; whole words, in any case.</small></label>
</div>
<label class="hw-gen__check"><input name="guard_size" type="checkbox"> Limit the input's length</label>
<div data-when="guard_size=on">
<label>Most characters<input name="max_chars" type="number" min="1" value="4000"></label>
</div>
<label class="hw-gen__check"><input name="guard_tool_secrets" type="checkbox"> Redact secrets in tool results</label>
<label class="hw-gen__check"><input name="guard_secrets" type="checkbox"> Block secrets in the output</label>
<label class="hw-gen__check"><input name="guard_citations" type="checkbox"> Require citations of retrieved documents in the output</label>
<label class="hw-gen__check"><input name="guard_stream" type="checkbox"> Cut a stream that leaks a secret</label>
<label>Mode for these guards<select name="guard_mode"><option value="log_only">log_only: record what they would do (shadow mode)</option><option value="enforce">enforce: act on what they find</option></select><small>New guards start in shadow mode, until evals show they are right.</small></label>
</fieldset>
<fieldset data-when="runner=session|workflow">
<legend>Retrieval</legend>
<label>Knowledge base<input name="kb_file" placeholder="data/kb.yaml"><small>Optional: a YAML file of documents your code fetches with <code>s.context("kb")</code>.</small></label>
</fieldset>
<fieldset>
<legend>Rules</legend>
<label>A tool call no rule matches<select name="default_effect"><option value="">is allowed (the default)</option><option value="require_approval">needs approval</option><option value="deny">is denied</option></select></label>
<label>Policy rule<input name="rule_when" placeholder="tool.name == 'refund_payment' &amp;&amp; args.amount_usd > 500"><small>Optional: a cel-lite expression over <code>tool</code>, <code>args</code>, <code>principal</code>, <code>tenant</code>, <code>task</code> and <code>labels</code>.</small></label>
<div class="hw-gen__row">
<label>Then<select name="rule_effect"><option value="deny">deny</option><option value="require_approval">require approval</option><option value="allow">allow</option></select></label>
<label>Reason<input name="rule_reason" placeholder="Refunds over 500 USD go to finance."></label>
</div>
<label class="hw-gen__check"><input name="approve_risky" type="checkbox"> Approve every call to a high or critical risk tool</label>
<label>Business rule<input name="check_when" placeholder="size(output) > 2000"><small>Optional: true when the output breaks the rule, over <code>output</code>, <code>input</code> and <code>task</code>.</small></label>
<label>Message<input name="check_message" placeholder="keep the answer under 2000 characters"><small>Sent to the model with the request to repair its answer.</small></label>
<div class="hw-gen__row">
<label>Repairs<input name="max_repairs" type="number" min="0" placeholder="1"></label>
<label>After the last repair<select name="on_failure"><option value="">the profile's choice</option><option value="block">block the run</option><option value="escalate">escalate to a person</option></select></label>
</div>
</fieldset>
<fieldset>
<legend>Approvals, state and telemetry</legend>
<label>Approval requests go to<select name="approvals"><option value="">memory: your app polls for them (the default)</option><option value="console">console: one line each, for local development</option><option value="webhook">webhook: a POST to a URL</option><option value="callback">callback: a function of yours</option></select></label>
<div data-when="approvals=webhook"><label>URL<input name="webhook_url" value="https://example.com/approvals"></label></div>
<div data-when="approvals=callback"><label>Function<input name="callback_handler" value="app.approvals:notify"></label></div>
<label>Approval timeout<input name="approval_timeout" placeholder="24h"></label>
<label>State<select name="state"><option value="">memory: lost when the process stops (the default)</option><option value="sqlite">sqlite: a file, so runs survive a restart</option></select></label>
<div data-when="state=sqlite"><label>Path<input name="state_path" value=".harness/state.db"></label></div>
<label class="hw-gen__check"><input name="record" type="checkbox"> Record runs for replay (recordings hold content)</label>
<label>Telemetry<select name="exporter"><option value="">none: your app sets up OpenTelemetry (the default)</option><option value="console">console: print spans</option><option value="otlp">otlp: send them to a collector</option></select></label>
<div data-when="exporter=otlp"><label>Endpoint<input name="endpoint" value="http://localhost:4318"></label></div>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
<div class="hw-gen__out">
<div class="hw-gen__bar"><strong>harness.yaml</strong><span><button type="button" id="hw-gen-copy" class="md-button md-button--primary">Copy</button> <button type="button" id="hw-gen-download" class="md-button">Download</button></span></div>
<pre><code id="hw-gen-yaml">The spec appears here once the page has loaded.</code></pre>
<p><strong>Install</strong> what it uses:</p>
<pre><code id="hw-gen-install"></code></pre>
<div><p><strong>Create</strong> the files it refers to, next to <code>harness.yaml</code>:</p><ul id="hw-gen-files"></ul></div>
</div>
</div>

<noscript>The generator needs JavaScript. Without it, start from a template with <code>harnessweaver init</code> (see Project templates).</noscript>

## Next steps

1. Save the spec as `harness.yaml` at the root of your project, and run the install commands. The CLI is a development dependency.
2. Create the files the spec refers to. `spec validate` imports every type and function the spec names and reads every prompt, manifest and knowledge base file, so it fails on any that is missing. The eval set is read only by `harnessweaver eval run`. The [Tutorial](../tutorial/index.md) shows each kind of file, and [Tool manifests](../reference/tool-manifests.md) what a manifest holds.
3. Check it:

    ```console
    $ uv run harnessweaver spec validate
    $ uv run harnessweaver doctor
    ```

    `spec validate` loads the spec as your app will and prints the [adoption level](../concepts/adoption-levels.md) it reaches. `doctor` says what the next level needs and lists the guards still in shadow mode. `harnessweaver spec explain` shows every value the profile and your org baseline add.

4. Run it from your code with `hw.load("harness.yaml")` and `await harness.run("support", ...)`, as in the [Quickstart](quickstart.md). To try it with no network and no keys, add an offline overlay with a scripted model, as described in [Models and environments](../tutorial/models.md).

## What the profiles add

Every spec also starts from the framework's defaults: no telemetry export, no content capture, manifests required for every tool, one repair, and in-memory approvals and state.

| Profile | Guards | Deadline |
| --- | --- | --- |
| `extraction` | PII redacted from the input, secrets blocked in the output. A failed repair escalates | 1 minute |
| `rag` | PII redacted and injection blocked in the input, injection blocked in retrieved documents, secrets blocked in the output | 30 seconds |
| `agent` | Injection blocked in the input, secrets redacted from tool results and blocked in the output. At most 20 tool calls | 2 minutes |
| `workflow` | Secrets blocked in the output | 5 minutes |
| `chat` | PII redacted from the input, secrets cut from the stream and blocked in the output | 1 minute |

Each is listed in full in [Built-in profiles](../reference/profiles.md). A guard you add on this page with the same check as the profile's runs as well; leave it unticked unless you want it in another mode.

## What each choice writes

| Choice | In the spec | Reference |
| --- | --- | --- |
| The app | `metadata` | [metadata](../reference/spec.md#metadata) |
| Profile and org baseline | `extends` | [Layers, locks and bounds](../advanced/layers.md) |
| Model | `models`, with the provider's own settings next to `provider` | [Models](../reference/providers.md#models) |
| The task | `tasks.<name>`: its runner, prompt, input and output types, tools and budget | [tasks](../reference/spec.md#tasks) |
| Eval set | `evals.<task>` | [evals](../reference/spec.md#evals) |
| Guardrails | `guardrails.<stage>`, each guard with an `id`, so a later layer can change it | [Guards](../reference/providers.md#guards) |
| Knowledge base | `context.kb`, a `memory` source with at most three documents per fetch | [Context sources](../reference/providers.md#context-sources) |
| Rules | `policy` and `validation`, and `tools.approval_by_risk` | [policy](../reference/spec.md#policy), [validation](../reference/spec.md#validation) |
| Approvals, state and telemetry | `approvals`, `state` and `observability` | [approvals](../reference/spec.md#approvals), [state](../reference/spec.md#state), [observability](../reference/spec.md#observability) |

Optional settings you leave empty or at their default are left out of the spec, so the framework's defaults, the profile and your org baseline decide them. Names, expressions and text you type are quoted wherever YAML would read them as something else.

## What it leaves out

The page writes one task and the settings most apps start with. These are in the [Section reference](../reference/spec.md), for when you need them:

- more tasks, each with its own runner, budget and guards;
- routing (`routing`), memory (`memory`), middleware from plugins (`middleware`) and guards that run in harnessd (`where: sidecar`);
- a provider's other settings, such as timeouts and prices (`models.prices`);
- org profiles of your own, with `locks`, `bounds` and `require_level` ([Write an org baseline](../how-to/org-baseline.md)).
