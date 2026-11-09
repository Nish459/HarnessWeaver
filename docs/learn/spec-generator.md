---
hide:
  - toc
---

# Spec generator

Pick a document and what it needs, and this page writes the YAML as you go. It writes every document a HarnessWeaver project is made of:

- an **app spec** (`harness.yaml`, `kind: Harness`), for a task the harness runs, a session your code opens, or a client or agent your app already has, in Python or TypeScript;
- a **profile** (`kind: Profile`): an org baseline, a profile your team shares between its apps, or one a plugin ships, with locks, bounds and a required adoption level;
- an **environment overlay** (`harness.<env>.yaml`): a scripted model for tests and demos, or a deployment's gateway, telemetry and state;
- a **tool manifest** (`kind: Tool`), which every tool needs before it can run;
- an **eval suite**, the cases `harnessweaver eval run` grades.

Everything runs in your browser: nothing you type leaves the page. Copy or download the document, create the files it lists, and check it with the command shown under it.

<div class="hw-gen" id="hw-gen">
<fieldset class="hw-gen__docs">
<legend>What are you writing?</legend>
<div class="hw-gen__pills">
<label><input type="radio" name="hw-gen-doc" value="harness" checked><span>App spec<small>harness.yaml</small></span></label>
<label><input type="radio" name="hw-gen-doc" value="profile"><span>Profile<small>an org baseline, or shared settings</small></span></label>
<label><input type="radio" name="hw-gen-doc" value="overlay"><span>Environment overlay<small>harness.&lt;env&gt;.yaml</small></span></label>
<label><input type="radio" name="hw-gen-doc" value="tool"><span>Tool manifest<small>tools/&lt;name&gt;.tool.yaml</small></span></label>
<label><input type="radio" name="hw-gen-doc" value="eval"><span>Eval suite<small>evals/&lt;suite&gt;.yaml</small></span></label>
</div>
</fieldset>
<div class="hw-gen__forms">
<form data-doc="harness" class="hw-gen__form" autocomplete="off">
<input type="hidden" name="doc" value="harness">
<fieldset>
<legend>The app</legend>
<label>Name<input name="name" value="support-desk" required pattern="[a-z0-9][a-z0-9._\-]*"><small>Lowercase letters, digits, <code>.</code>, <code>_</code> and <code>-</code>.</small></label>
<label>Owner<input name="owner" value="support-team"><small>The team that owns it.</small></label>
<label>Risk tier<select name="risk_tier"><option value="internal">internal</option><option value="customer_facing">customer_facing</option><option value="takes_actions">takes_actions</option></select><small>Your org baseline picks the adoption level an app must reach by its tier.</small></label>
<label>Language<select name="language"><option value="python">Python</option><option value="typescript">TypeScript: sessions, with AI SDK models through wrapModel</option></select></label>
<label>How your code uses it<select name="style"><option value="task">task: the harness runs a task you define, with harness.run</option><option value="session">session: your code opens a governed session with no task</option><option value="wrap">wrap: govern a client or agent your app already has (Python)</option></select></label>
<div data-when="style=wrap&amp;language=python">
<label>What you wrap<select name="wraps"><option value="openai">an OpenAI client: harness.instrument(client)</option><option value="anthropic">an Anthropic client: harness.instrument(client)</option><option value="pydantic_ai">a Pydantic AI agent: harness.wrap(agent)</option></select><small>Each call becomes a governed run of its own, with the budget below.</small></label>
</div>
</fieldset>
<fieldset>
<legend>Starting point</legend>
<label>Profile<select name="profile"><option value="extraction">extraction: typed output from text</option><option value="rag">rag: answers from documents</option><option value="agent">agent: a model that calls tools</option><option value="workflow">workflow: a fixed pipeline of steps</option><option value="chat">chat: streamed conversation</option><option value="none">none: only the framework's defaults</option></select><small>The guards and the deadline the profile adds are listed below the form.</small></label>
<label>Org baseline<input name="baseline" placeholder="org://acme-baseline@^1"><small>Optional: your platform team's profile, which every app extends. Write one under Profile.</small></label>
</fieldset>
<fieldset data-when="style=task|session">
<legend>Model</legend>
<div>
<label>Provider<select name="provider"><option value="openai.chat">openai.chat: any OpenAI-compatible endpoint, such as LiteLLM</option><option value="anthropic.messages">anthropic.messages: Claude, through the Messages API</option><option value="scripted">scripted: canned answers, offline</option></select></label>
<div data-when="provider=openai.chat">
<label>Endpoint<input name="base_url" value="http://localhost:4000"><small>Usually your gateway, which holds the provider keys.</small></label>
<label>API key variable<input name="api_key_env" value="LITELLM_API_KEY"><small>The environment variable with the key. Keys never go in the spec.</small></label>
</div>
<div data-when="provider=anthropic.messages">
<label>Effort<select name="effort"><option value="">the model's default</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option></select></label>
</div>
<div data-when="provider=scripted">
<label>Reply<input name="reply" value="Hello."><small>What the scripted model answers, for trying the spec with no network and no keys.</small></label>
</div>
</div>
<div data-when="language=typescript"><small>Your TypeScript code passes its AI SDK model to <code>wrapModel</code>, under one of these aliases, for budgets and prices. The provider is for Python, which loads the spec in <code>spec validate</code> and runs the task in harnessd.</small></div>
<div data-when="provider=openai.chat|anthropic.messages">
<label>Model for the <code>fast</code> alias<input name="fast_model" value="your-fast-model"><small>The default alias. Your code and tasks name aliases, never models.</small></label>
<label>Model for the <code>strong</code> alias<input name="strong_model" placeholder="optional"></label>
<div class="hw-gen__row">
<label>Input, USD per million tokens<input name="price_in" type="number" min="0" step="0.01"></label>
<label>Output, USD per million tokens<input name="price_out" type="number" min="0" step="0.01"></label>
</div>
<small>Optional: the <code>fast</code> model's price, for when the gateway doesn't report a cost.</small>
</div>
</fieldset>
<fieldset data-when="style=task">
<legend>The task</legend>
<label>Name<input name="task" value="support"></label>
<div data-when="language=python">
<label>Runner<select name="runner"><option value="direct">direct: the harness calls the model, with a bounded tool loop</option><option value="session">session: your own async function</option><option value="workflow">workflow: your steps, in order</option><option value="pydantic_ai.agent">pydantic_ai.agent: a Pydantic AI agent</option></select></label>
</div>
<div data-when="runner=session&amp;language=python">
<label>Handler<input name="handler" value="app.flow:answer"><small><code>package.module:function</code>, called as <code>await answer(session, input)</code>.</small></label>
</div>
<div data-when="runner=workflow&amp;language=python">
<label>Steps<input name="steps" value="app.steps:clean, app.steps:classify, app.steps:reply"><small>Functions, comma-separated; each step runs after the one before it.</small></label>
</div>
<div data-when="runner=pydantic_ai.agent&amp;language=python">
<label>Agent<input name="agent" value="app.agent:support_agent"><small><code>package.module:attribute</code> of a Pydantic AI agent.</small></label>
</div>
<div data-when="runner=direct|pydantic_ai.agent&amp;language=python">
<label>Prompt<input name="prompt" value="support@1"><small>A versioned prompt, <code>name@version</code>, in <code>prompts/</code>. Empty for none.</small></label>
</div>
<div data-when="runner=direct|pydantic_ai.agent&amp;language=python || language=typescript">
<label>Tools<input name="tools" placeholder="lookup_order, refund_payment"><small>Tool names, comma-separated. Each needs a manifest; write one under Tool manifest.</small></label>
</div>
<label>Input type<input name="input" placeholder="app.models:Ticket"><small>Optional: the Pydantic model the input is checked against.</small></label>
<label>Output type<input name="output" value="str"><small><code>str</code> for text, or a Pydantic model such as <code>app.models:Triage</code>.</small></label>
<label class="hw-gen__check" data-when="language=python"><input name="evals" type="checkbox" checked> Add a golden eval set</label>
</fieldset>
<fieldset>
<legend>Budget</legend>
<div class="hw-gen__row">
<label>Model calls<input name="max_model_calls" type="number" min="0" value="3"></label>
<label>Tool calls<input name="max_tool_calls" type="number" min="0"></label>
<label>Cost, USD<input name="max_usd" type="number" min="0" step="0.01" value="0.05"></label>
<label>Deadline<input name="deadline" placeholder="30s"></label>
</div>
<small>For each run of the task, or, with no task, each run: each session, or each call to a wrapped client. Empty fields set no limit.</small>
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
<label class="hw-gen__check"><input name="guard_sidecar" type="checkbox"> Run these guards in harnessd, the sidecar</label>
<div data-when="guard_sidecar=on">
<label>harnessd URL<input name="sidecar_url" value="http://127.0.0.1:7070"><small>Its token is read from <code>HARNESSD_TOKEN</code>. For guards only Python has, from a TypeScript app.</small></label>
</div>
</fieldset>
<fieldset data-when="style=session || style=task&amp;runner=session|workflow&amp;language=python || language=typescript">
<legend>Your code</legend>
<label>Knowledge base<input name="kb_file" placeholder="data/kb.yaml"><small>Optional: a YAML file of documents your code fetches with <code>s.context("kb")</code>.</small></label>
<label>Router<input name="router" value="intent"><small>The name your code asks with <code>s.decide("intent", text=...)</code>.</small></label>
<label>Options<textarea name="router_options" rows="3" placeholder="billing: refund my order, I was charged twice&#10;other"></textarea><small>Optional: one option a line, with example texts after a colon. The closest examples pick the option.</small></label>
<label>Fallback option<input name="router_default" placeholder="the last option"></label>
<label class="hw-gen__check"><input name="memory" type="checkbox"> Keep key-value memory, per tenant and principal (<code>s.memory</code>)</label>
<div data-when="memory=on">
<label>Entries expire after<input name="memory_ttl" placeholder="30d"></label>
</div>
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
<fieldset data-when="language=python">
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
<div data-when="exporter=console|otlp"><label>Service name<input name="service_name" placeholder="support-desk"></label></div>
</fieldset>
<fieldset>
<legend>Plugins</legend>
<label data-when="language=python">Your own plugin<input name="plugin_local" placeholder="app.harness_plugin"><small>Optional: a module of this app that exposes <code>plugin = hw.Plugin(...)</code>, for its own guards and middleware.</small></label>
<label>Middleware<input name="middleware" placeholder="acme.no_weekend_refunds"><small>Optional: middleware from plugins, <code>namespace.name</code>, comma-separated, run in this order.</small></label>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
<form data-doc="profile" class="hw-gen__form" autocomplete="off" hidden>
<input type="hidden" name="doc" value="profile">
<fieldset>
<legend>The profile</legend>
<label>Who it is for<select name="profile_kind"><option value="org">an org baseline: the platform team publishes it for every app</option><option value="team">your team's apps: it lives next to them, in .harness/profiles/</option><option value="plugin">a plugin's users: the plugin ships it</option></select><small>Locks bind apps only in a profile they can't edit: an org baseline or a plugin's.</small></label>
<div data-when="profile_kind=plugin"><label>Plugin namespace<input name="plugin_ns" value="acme"></label></div>
<label>Name<input name="name" value="acme-baseline" required pattern="[a-z0-9][a-z0-9._\-]*"></label>
<label>Version<input name="version" value="1.0.0" required pattern="[0-9]+\.[0-9]+\.[0-9]+.*"><small>SemVer. A new lock or a tighter bound is a major version.</small></label>
<label>Owner<input name="owner" value="platform-security"></label>
<label>Description<input name="description" placeholder="optional"></label>
<label>Extends<input name="extends" placeholder="org://acme-root@^2"><small>Optional: profiles it builds on, comma-separated.</small></label>
</fieldset>
<fieldset>
<legend>Plugins and models</legend>
<label>Allowed plugins<input name="allow" value="openai, anthropic, otel"><small>Namespaces apps may use (empty for any). The core's own providers are always allowed, and a plugin's profile allows its plugin.</small></label>
<label class="hw-gen__check"><input name="lock_allow" type="checkbox" checked> Lock the list</label>
<label>Allowed model aliases<input name="allowed_aliases" value="fast, strong"><small>The aliases your gateway serves; an app may name no other.</small></label>
<label>Model gateway<select name="provider"><option value="">none: each app sets its own</option><option value="openai.chat">openai.chat: any OpenAI-compatible endpoint, such as LiteLLM</option><option value="anthropic.messages">anthropic.messages: Claude, through the Messages API</option></select></label>
<div data-when="provider=openai.chat">
<label>Endpoint<input name="base_url" placeholder="https://llm-gateway.internal.example"></label>
<label>API key variable<input name="api_key_env" placeholder="LITELLM_API_KEY"></label>
</div>
<div data-when="provider=anthropic.messages">
<label>Effort<select name="effort"><option value="">the model's default</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option></select></label>
</div>
<div data-when="provider=openai.chat|anthropic.messages">
<label>Model for the <code>fast</code> alias<input name="fast_model" placeholder="the gateway's name for it"></label>
<label>Model for the <code>strong</code> alias<input name="strong_model" placeholder="optional"></label>
<label class="hw-gen__check"><input name="lock_gateway" type="checkbox"> Lock the provider and endpoint</label>
</div>
</fieldset>
<fieldset>
<legend>Guardrails</legend>
<label class="hw-gen__check"><input name="guard_pii" type="checkbox" checked> Redact PII in the input</label>
<label class="hw-gen__check"><input name="guard_injection" type="checkbox"> Block prompt injection in the input</label>
<label class="hw-gen__check"><input name="guard_topics" type="checkbox"> Block input about denied topics</label>
<div data-when="guard_topics=on">
<label>Denied words<input name="topics" placeholder="lawsuit, diagnosis, prescription"></label>
</div>
<label class="hw-gen__check"><input name="guard_size" type="checkbox"> Limit the input's length</label>
<div data-when="guard_size=on">
<label>Most characters<input name="max_chars" type="number" min="1" value="4000"></label>
</div>
<label class="hw-gen__check"><input name="guard_tool_secrets" type="checkbox"> Redact secrets in tool results</label>
<label class="hw-gen__check"><input name="guard_secrets" type="checkbox" checked> Block secrets in the output</label>
<label class="hw-gen__check"><input name="guard_citations" type="checkbox"> Require citations of retrieved documents in the output</label>
<label class="hw-gen__check"><input name="guard_stream" type="checkbox"> Cut a stream that leaks a secret</label>
<label>Mode<select name="guard_mode"><option value="log_only">log_only: record what they would do (shadow mode)</option><option value="enforce">enforce: act on what they find</option></select><small>Promote them to enforce here, once evals show they are right.</small></label>
<label class="hw-gen__check"><input name="lock_guards" type="checkbox" checked> Lock each guard by its id: apps can add their own, not change these</label>
</fieldset>
<fieldset>
<legend>Tools and rules</legend>
<label class="hw-gen__check"><input name="lock_manifest" type="checkbox" checked> Every tool needs a manifest, locked</label>
<label class="hw-gen__check"><input name="approve_risky" type="checkbox" checked> Approve every call to a high or critical risk tool</label>
<label class="hw-gen__check" data-when="approve_risky=on"><input name="lock_risk" type="checkbox" checked> Lock that</label>
<label>Untrusted content, private data and egress in one run<select name="trifecta"><option value="">need approval (the default)</option><option value="block">are blocked</option></select></label>
<label>A tool call no rule matches<select name="default_effect"><option value="">is allowed (the default)</option><option value="require_approval">needs approval</option><option value="deny">is denied</option></select></label>
<label>Policy rule<input name="rule_when" placeholder="'contractor' in principal.roles &amp;&amp; tool.name == 'refund_payment'"></label>
<div class="hw-gen__row">
<label>Then<select name="rule_effect"><option value="deny">deny</option><option value="require_approval">require approval</option><option value="allow">allow</option></select></label>
<label>Reason<input name="rule_reason" placeholder="Contractors can't refund."></label>
</div>
<label class="hw-gen__check"><input name="lock_rule" type="checkbox" checked> Lock the rule, if there is one</label>
<div class="hw-gen__row">
<label>Repairs<input name="max_repairs" type="number" min="0" placeholder="1"></label>
<label>After the last repair<select name="on_failure"><option value="">block (the default)</option><option value="block">block the run</option><option value="escalate">escalate to a person</option></select></label>
</div>
</fieldset>
<fieldset>
<legend>Budgets and bounds</legend>
<div class="hw-gen__row">
<label>Model calls<input name="max_model_calls" type="number" min="0"></label>
<label>Tool calls<input name="max_tool_calls" type="number" min="0"></label>
<label>Cost, USD<input name="max_usd" type="number" min="0" step="0.01" value="2.00"></label>
<label>Deadline<input name="deadline" value="5m"></label>
</div>
<small>Each run's budget, which apps may lower or raise up to the bounds.</small>
<div class="hw-gen__row">
<label>Most a run may cost, USD<input name="bound_run_usd" type="number" min="0" step="0.01" value="5.00"></label>
<label>Longest a run may take<input name="bound_run_deadline" value="30m"></label>
<label>Most a task may cost, USD<input name="bound_task_usd" type="number" min="0" step="0.01" value="2.00"></label>
<label>Most tool calls a task may make<input name="bound_task_tool_calls" type="number" min="0"></label>
<label>Most repairs<input name="bound_repairs" type="number" min="0"></label>
</div>
<small>Bounds: a value above one fails loading, and is never clamped.</small>
</fieldset>
<fieldset>
<legend>Required level and locks</legend>
<label class="hw-gen__check"><input name="lock_capture" type="checkbox" checked> No prompts or outputs in telemetry, locked</label>
<div class="hw-gen__row">
<label>Every app<select name="level_default"><option value="L0">L0 Observe</option><option value="L1" selected>L1 Guard</option><option value="L2">L2 Govern</option><option value="L3">L3 Orchestrate</option><option value="L4">L4 Improve</option></select></label>
<label>internal<select name="level_internal"><option value="">as every app</option><option value="L1">L1</option><option value="L2">L2</option><option value="L3">L3</option><option value="L4">L4</option></select></label>
<label>customer_facing<select name="level_customer_facing"><option value="">as every app</option><option value="L1">L1</option><option value="L2" selected>L2</option><option value="L3">L3</option><option value="L4">L4</option></select></label>
<label>takes_actions<select name="level_takes_actions"><option value="">as every app</option><option value="L1">L1</option><option value="L2">L2</option><option value="L3" selected>L3</option><option value="L4">L4</option></select></label>
</div>
<small>The adoption level an app must reach, by its risk tier. An app below it fails loading.</small>
<label>Other locks<input name="locks" placeholder="state.use, routing.*"><small>Optional: more paths, comma-separated: <code>a.b</code>, <code>list[id]</code>, <code>*</code> for any key and <code>[*]</code> for any item.</small></label>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
<form data-doc="overlay" class="hw-gen__form" autocomplete="off" hidden>
<input type="hidden" name="doc" value="overlay">
<fieldset>
<legend>The environment</legend>
<label>Name<input name="env" value="offline" required pattern="[A-Za-z0-9_\-]+"><small><code>HARNESSWEAVER_ENV=offline</code> merges <code>harness.offline.yaml</code> over <code>harness.yaml</code>. An overlay holds sections only.</small></label>
</fieldset>
<fieldset>
<legend>Model</legend>
<label>Provider<select name="provider"><option value="scripted">scripted: canned answers, for tests and demos</option><option value="openai.chat">openai.chat: this environment's gateway</option><option value="anthropic.messages">anthropic.messages: Claude</option><option value="">the app spec's</option></select></label>
<div data-when="provider=scripted"><label>Reply<input name="reply" value="Hello."><small>What the model answers. For one answer per request, add <code>rules</code> by hand (Models reference).</small></label></div>
<div data-when="provider=openai.chat">
<label>Endpoint<input name="base_url" placeholder="https://llm-gateway.internal.example"></label>
<label>API key variable<input name="api_key_env" placeholder="the app spec's"></label>
</div>
<div data-when="provider=anthropic.messages">
<label>Effort<select name="effort"><option value="">the model's default</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option></select></label>
</div>
<div data-when="provider=openai.chat|anthropic.messages">
<label>Model for the <code>fast</code> alias<input name="fast_model" placeholder="the app spec's"></label>
<label>Model for the <code>strong</code> alias<input name="strong_model" placeholder="the app spec's"></label>
</div>
</fieldset>
<fieldset>
<legend>Telemetry, state and approvals</legend>
<label>Telemetry<select name="exporter"><option value="">the app spec's</option><option value="console">console: print spans</option><option value="otlp">otlp: send them to a collector</option></select></label>
<div data-when="exporter=otlp"><label>Endpoint<input name="endpoint" value="http://otel-collector:4318"></label></div>
<div data-when="exporter=console|otlp"><label>Service name<input name="service_name" placeholder="support-desk"></label></div>
<label>State<select name="state"><option value="">the app spec's</option><option value="memory">memory: lost when the process stops</option><option value="sqlite">sqlite: a file, so runs survive a restart</option></select></label>
<div data-when="state=sqlite"><label>Path<input name="state_path" value=".harness/state.db"></label></div>
<label>Approval requests go to<select name="approvals"><option value="">the app spec's channel</option><option value="console">console: one line each</option><option value="webhook">webhook: a POST to a URL</option></select></label>
<div data-when="approvals=webhook"><label>URL<input name="webhook_url" value="https://example.com/approvals"></label></div>
<label>harnessd URL<input name="sidecar_url" placeholder="http://harnessd:7070"><small>Optional: where this environment's sidecar runs, for guards declared <code>where: sidecar</code>.</small></label>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
<form data-doc="tool" class="hw-gen__form" autocomplete="off" hidden>
<input type="hidden" name="doc" value="tool">
<fieldset>
<legend>The tool</legend>
<label>Name<input name="name" value="lookup_order" required pattern="[A-Za-z_.\-][A-Za-z0-9_.\-]*"><small>As the model and the spec see it.</small></label>
<label>Version<input name="version" value="1.0.0"></label>
<label>Owner<input name="owner" placeholder="orders-team"></label>
<label>Description<input name="description" value="Look up an order by its id."><small>What the model is told the tool does.</small></label>
<label>Arguments<textarea name="arguments" rows="3">order_id: string</textarea><small>One a line, <code>name: type</code> (string, number, integer, boolean, array or object), with <code>?</code> after an optional one's name.</small></label>
</fieldset>
<fieldset>
<legend>How it is reached</legend>
<label>Transport<select name="transport"><option value="native">native: a Python function</option><option value="http">http: a POST to a URL</option><option value="code">code: code run in the Monty sandbox</option></select></label>
<div data-when="transport=native"><label>Handler<input name="handler" placeholder="app.tools:lookup_order"><small><code>package.module:function</code>; the tool's name in <code>app.tools</code> when empty.</small></label></div>
<div data-when="transport=http">
<label>URL<input name="url" value="https://example.com/tools/lookup_order"></label>
<label>Headers<input name="headers_env" placeholder="Authorization=ORDERS_TOKEN"><small>Optional: <code>Header=VARIABLE</code>, comma-separated; each value is read from the environment.</small></label>
</div>
<div data-when="transport=code"><label>Argument with the code<input name="code_arg" value="code"><small>The other arguments are the code's globals. Needs <code>harnessweaver-monty</code>.</small></label></div>
<label>Timeout<input name="timeout" placeholder="30s"></label>
</fieldset>
<fieldset>
<legend>What it may touch</legend>
<div class="hw-gen__row">
<label>Side effect<select name="side_effect"><option value="none">none</option><option value="read" selected>read</option><option value="write_internal">write_internal</option><option value="write_external">write_external</option><option value="destructive">destructive</option></select></label>
<label>Risk<select name="risk"><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></label>
</div>
<label>Data it reads<input name="data_access" placeholder="pii:customer"><small>Comma-separated; a <code>pii:</code> entry marks the run as having seen private data.</small></label>
<label>Hosts it sends data to<input name="egress" placeholder="payments.internal.example"><small>A tool with egress is checked for the lethal trifecta.</small></label>
<label>Scopes<input name="scopes" placeholder="orders:read"></label>
<label>Tenants<input name="tenants" placeholder="all of them"></label>
<div class="hw-gen__row">
<label>Calls per principal<input name="rate_principal" placeholder="10/m"></label>
<label>Calls per tenant<input name="rate_tenant" placeholder="200/h"></label>
</div>
</fieldset>
<fieldset>
<legend>Approval and output</legend>
<label>Needs approval when<input name="approval_when" placeholder="args.amount_usd > 100"><small>Optional: a cel-lite expression; true, or one that can't be evaluated, asks a person.</small></label>
<label>Approver role<input name="approver_role" placeholder="finance"></label>
<label>Most bytes of output<input name="max_bytes" type="number" min="1" placeholder="20000"></label>
<label class="hw-gen__check"><input name="sanitize_pii" type="checkbox"> Redact PII in its results</label>
<label class="hw-gen__check"><input name="sanitize_instructions" type="checkbox"> Strip instructions from its results</label>
<label>Its results are<select name="label"><option value="untrusted">untrusted (the default)</option><option value="trusted">trusted</option></select></label>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
<form data-doc="eval" class="hw-gen__form" autocomplete="off" hidden>
<input type="hidden" name="doc" value="eval">
<fieldset>
<legend>The suite</legend>
<label>Name<input name="suite" value="golden" required pattern="[A-Za-z0-9_\-]+"><small>golden for cases the task must get right, redteam for cases it must stop.</small></label>
<label>Task<input name="task" value="support"></label>
<label>Share of cases that must pass<input name="pass_rate" type="number" min="0" max="1" step="0.05" placeholder="1.0"></label>
</fieldset>
<fieldset>
<legend>Graders, for every case</legend>
<label class="hw-gen__check"><input name="grade_schema" type="checkbox" checked> The output matches the task's output type</label>
<label class="hw-gen__check"><input name="grade_exact" type="checkbox"> The output equals the expected one</label>
<label>Fields that equal the expected ones<input name="field_equals" placeholder="category, total"></label>
<label>Text the output contains<input name="contains" placeholder="refund"></label>
<label>How the run ends<select name="status"><option value="">any way</option><option value="completed">completed</option><option value="blocked">blocked</option><option value="escalated">escalated</option><option value="awaiting_approval">awaiting_approval</option></select></label>
<label>Guards that fire<input name="guard_fired" placeholder="extraction-pii"><small>Ids or names; a guard in shadow mode counts too.</small></label>
<label>Rubric for a model judge<input name="rubric" placeholder="The answer is polite and correct."></label>
</fieldset>
<fieldset>
<legend>The first case</legend>
<label>Id<input name="case_id" value="first"></label>
<label>Input<textarea name="case_input" rows="2">Where is my order?</textarea><small>Text, or JSON for a typed input, such as <code>{"text": "..."}</code>.</small></label>
<label>Expected output<textarea name="case_expect" rows="2" placeholder='{"category": "billing"}'></textarea></label>
</fieldset>
<button type="reset" class="md-button">Start over</button>
</form>
</div>
<div class="hw-gen__out">
<div class="hw-gen__bar"><strong id="hw-gen-file">harness.yaml</strong><span><button type="button" id="hw-gen-copy" class="md-button md-button--primary">Copy</button> <button type="button" id="hw-gen-download" class="md-button">Download</button></span></div>
<pre><code id="hw-gen-yaml">The document appears here once the page has loaded.</code></pre>
<div data-block><p><strong>Install</strong> what it uses:</p><pre><code id="hw-gen-install"></code></pre></div>
<div><p><strong>Create</strong> the files it refers to, next to <code>harness.yaml</code>:</p><ul id="hw-gen-files"></ul></div>
<div data-block><p><strong>Check</strong> it, from the app's folder:</p><pre><code id="hw-gen-check"></code></pre></div>
<div data-block><p><strong>Use</strong> it:</p><pre><code id="hw-gen-use"></code></pre></div>
</div>
</div>

<noscript>The generator needs JavaScript. Without it, start from a template with <code>harnessweaver init</code> (see Project templates).</noscript>

## Next steps

Run the commands with `uv run` in a Python project; the CLI is one of its development dependencies.

**An app spec.** Save it as `harness.yaml` at the root of your project, run the install commands and create the files it lists. `spec validate` imports every type and function the spec names and reads every prompt, manifest and knowledge base file, so it fails on any that is missing; the eval set is read only by `harnessweaver eval run`. It prints the [adoption level](../concepts/adoption-levels.md) the spec reaches, and `harnessweaver doctor` says what the next level needs and lists the guards still in shadow mode. When the spec extends an org baseline, point the CLI at it with `--profile-dir` or `HARNESSWEAVER_PROFILE_PATH`. The [Tutorial](../tutorial/index.md) shows each kind of file, and [Integration styles](../concepts/integration-styles.md) each way to use the spec.

**A profile.** An org baseline goes in a directory on every app's `HARNESSWEAVER_PROFILE_PATH`, and a team's profile in `.harness/profiles/` next to its apps; a plugin lists its profile in `hw.Plugin(profiles=...)`. Apps pin a version range, so a breaking change never reaches them unannounced. Test it by trying to break each lock and bound, as in [Write an org baseline](../how-to/org-baseline.md), and see every value it adds to an app with `harnessweaver spec explain`.

**An overlay.** Save it next to `harness.yaml`. It changes only what it names. With the offline overlay, `harnessweaver eval run -e offline` and your tests run with no network and no keys ([Models and environments](../tutorial/models.md)).

**A tool manifest.** Save it in `tools/`, list the tool in the task's `tools`, then pin it: `tools pin` writes the `definition_digest` that pins its name, description and arguments, so a tool changed without review can't run, and `doctor` checks the pin. [Tool manifests](../reference/tool-manifests.md) lists every field.

**An eval suite.** Save it in `evals/`, name it in the spec's `evals` section and add cases. [Evals](../tutorial/evals.md) lists the graders and how baselines catch a regression.

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

| Document | Choice | In the document | Reference |
| --- | --- | --- | --- |
| App spec | The app, its profile and org baseline | `metadata`, `extends` | [metadata](../reference/spec.md#metadata), [Layers, locks and bounds](../advanced/layers.md) |
| | How your code uses it | A task in `tasks`, or no task and a budget for each run in `budgets.per_run` | [Integration styles](../concepts/integration-styles.md) |
| | Model | `models`, with the provider's own settings next to `provider`, and `prices` | [Models](../reference/providers.md#models) |
| | The task and its budget | `tasks.<name>`: its runner, prompt, input and output types, tools and budget; `evals.<task>` | [tasks](../reference/spec.md#tasks), [evals](../reference/spec.md#evals) |
| | Guardrails | `guardrails.<stage>`, each guard with an `id`, so a later layer can change it; `sidecar` for guards in harnessd | [Guards](../reference/providers.md#guards), [The sidecar](../advanced/sidecar.md) |
| | Your code | `context.kb`, a `memory` source with at most three documents per fetch; `routing.<router>`, with a `lexical` stage; `memory` | [Context sources](../reference/providers.md#context-sources), [Routing stages](../reference/providers.md#routing-stages) |
| | Rules | `policy`, `validation` and `tools.approval_by_risk` | [policy](../reference/spec.md#policy), [validation](../reference/spec.md#validation) |
| | Approvals, state and telemetry | `approvals`, `state` and `observability` | [approvals](../reference/spec.md#approvals), [state](../reference/spec.md#state), [observability](../reference/spec.md#observability) |
| | Plugins | `plugins.local` and `middleware` | [Plugins](../advanced/plugins.md), [Middleware](../advanced/middleware.md) |
| Profile | Everything above it holds, plus | `locks`, `bounds` and `require_level`; its guards and rule get ids that start with its name | [Profiles only](../reference/spec.md#profiles-only) |
| Overlay | The environment's settings | The sections it changes, with `kind: Overlay` | [Layers](../advanced/layers.md#the-layers) |
| Tool manifest | The tool | `metadata` and `spec` | [Tool manifests](../reference/tool-manifests.md) |
| Eval suite | The graders and a case | `suite`, `task`, `graders`, `thresholds` and `cases` | [Graders](../reference/providers.md#graders) |

Optional settings you leave empty or at their default are left out, so the framework's defaults, the profiles and your org baseline decide them. Names, expressions and text you type are quoted wherever YAML would read them as something else.

## What it leaves out

The page writes the settings most projects start with. These are in the [Section reference](../reference/spec.md), for when you need them:

- more tasks in one spec, each with its own runner, budget and guards, and a task's own guards and approvals;
- routing stages other than `lexical` (`rules`, `semantic`, `llm`), and more than one router;
- guard settings beyond the ones above, such as `regex.deny` patterns and `llm.judge`, and `parallel` or `timeout` on a guard;
- a provider's other settings, such as timeouts, and the scripted model's `rules`;
- an MCP tool (`transport: mcp` is *planned*), and a tool's `input_schema` beyond types: patterns, ranges, nesting;
- the policy test file `harnessweaver policy test` reads.
