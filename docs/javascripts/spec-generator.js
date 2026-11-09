/*
 * The spec generator's writers (docs/learn/spec-generator.md). Each turns the values of one
 * of the page's forms into one of the framework's YAML documents: an app spec (kind:
 * Harness), a profile (kind: Profile), an environment overlay (kind: Overlay), a tool
 * manifest (kind: Tool) or an eval suite.
 *
 * buildSpec takes what FormData gives (strings, and "on" for a checked box), with `doc`
 * naming the document, and returns {file, yaml, files, install, check, use}: where to save
 * the document, its text, the files it refers to, the commands that install what it uses
 * and check it, and a snippet that shows how it is used. The writers touch no page, so
 * docs_src/tests runs them under Node.js and checks that every document they write loads.
 * spec-generator-page.js wires them to the page. Nothing typed into the form leaves it.
 */

(function () {
  "use strict";

  var API_VERSION = "harnessweaver/v1";

  /* What each model provider's aliases default to. */
  var MODELS = {
    "openai.chat": { fast: "your-fast-model", strong: "" },
    "anthropic.messages": { fast: "claude-haiku-5-5", strong: "claude-opus-5-5" },
    scripted: { fast: "", strong: "" },
  };

  /* The guards the forms offer: its checkbox, the stage, and the guard (its id a suffix). */
  var GUARDS = [
    ["guard_pii", "input", { id: "pii", use: "pii.regex", action: "redact" }],
    ["guard_injection", "input", { id: "injection", use: "injection.heuristic", action: "block" }],
    ["guard_topics", "input", { id: "topics", use: "topic.deny", action: "block" }],
    ["guard_size", "input", { id: "size", use: "size.limit", action: "block" }],
    ["guard_tool_secrets", "tool_result", { id: "tool-secrets", use: "secrets.scan", action: "redact" }],
    ["guard_secrets", "output", { id: "secrets", use: "secrets.scan", action: "block" }],
    ["guard_citations", "output", { id: "citations", use: "grounded.citations", action: "repair" }],
    ["guard_stream", "stream", { id: "stream-secrets", use: "secrets.scan", action: "block" }],
  ];

  /* ---- YAML ---- */

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  /* Whether a value is worth writing: not unset, not empty text, not an empty map or list. */
  function present(value) {
    if (value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return !isObject(value) || Object.keys(value).length > 0;
  }

  /* The value without what isn't worth writing, at any depth. */
  function prune(value) {
    if (Array.isArray(value)) return value.map(prune).filter(present);
    if (!isObject(value)) return value;
    var kept = {};
    Object.keys(value).forEach(function (key) {
      var item = prune(value[key]);
      if (present(item)) kept[key] = item;
    });
    return kept;
  }

  /*
   * One scalar, plain when YAML (1.2, and the 1.1 that older readers use) reads it back as
   * the same text, else double-quoted: a JSON string is a valid YAML one. Plain text here
   * starts with a word character or "/", holds no space and no ": " or " #", doesn't end in
   * ":", and isn't a number, a boolean or null.
   */
  function scalar(value) {
    if (typeof value !== "string") return String(value);
    var plain = /^[\w/][\w./@:-]*$/.test(value) && !value.endsWith(":") &&
      isNaN(Number(value)) && !/^(true|false|null|yes|no|on|off|y|n)$/i.test(value);
    return plain ? value : JSON.stringify(value);
  }

  /* A scalar inside [...], where a ":" also needs quotes for some readers. */
  function flowScalar(value) {
    return typeof value === "string" && value.indexOf(":") >= 0 ? JSON.stringify(value) : scalar(value);
  }

  /*
   * The lines of a map or a list, in block style, each starting with `indent`. A map's
   * maps and its lists of maps go on the lines below their key, as does a list of scalars
   * too long for one line; a shorter one stays on the key's line, as [a, b]. A list item
   * that is a map starts with "- " and its other keys line up under its first.
   */
  function lines(value, indent) {
    var out = [];
    if (Array.isArray(value)) {
      value.forEach(function (item) {
        if (!isObject(item)) {
          out.push(indent + "- " + scalar(item));
          return;
        }
        var inner = lines(item, indent + "  ");
        out.push(indent + "- " + inner[0].slice(indent.length + 2));
        out.push.apply(out, inner.slice(1));
      });
      return out;
    }
    Object.keys(value).forEach(function (key) {
      var item = value[key];
      var flow = Array.isArray(item) && !item.some(isObject) &&
        indent + scalar(key) + ": [" + item.map(flowScalar).join(", ") + "]";
      if (flow && flow.length <= 80) {
        out.push(flow);
      } else if (isObject(item) || Array.isArray(item)) {
        out.push(indent + scalar(key) + ":");
        out.push.apply(out, lines(item, indent + "  "));
      } else {
        out.push(indent + scalar(key) + ": " + scalar(item));
      }
    });
    return out;
  }

  /* ---- Reading a form ---- */

  /*
   * Readers for one form's values, and the list of files the document refers to. `need`
   * records one as {path, kind, name}: kind says what goes in it (a prompt, a Pydantic
   * model, a function, a Pydantic AI agent, a tool manifest, the documents to retrieve
   * from, an eval dataset, a plugin or a middleware), and name what it holds: the attribute
   * imported from it, the tool, the task, the plugin's namespace or the middleware.
   */
  function reader(values) {
    var files = [];
    var r = {
      files: files,
      text: function (key) {
        return String(values[key] || "").trim();
      },
      /* Comma-separated items. */
      list: function (key) {
        return r.text(key).split(",").map(function (item) { return item.trim(); }).filter(Boolean);
      },
      /* The lines of a text area. */
      lines: function (key) {
        return r.text(key).split("\n").map(function (line) { return line.trim(); }).filter(Boolean);
      },
      number: function (key) {
        return r.text(key) === "" || isNaN(Number(r.text(key))) ? undefined : Number(r.text(key));
      },
      on: function (key) {
        return values[key] === "on";
      },
      need: function (path, kind, name) {
        var file = name ? { path: path, kind: kind, name: name } : { path: path, kind: kind };
        var known = files.some(function (f) {
          return f.path === path && f.kind === kind && f.name === file.name;
        });
        if (!known) files.push(file);
      },
      /* An import path, package.module:attribute, is a file next to the spec. */
      imports: function (ref, kind) {
        if (!ref) return undefined;
        var parts = ref.split(":");
        r.need(parts[0].replace(/\./g, "/") + ".py", kind, parts[1]);
        return ref;
      },
    };
    return r;
  }

  /* Typed text as a value: what it means as JSON, when it is JSON, else the text itself. */
  function typed(text) {
    if (text === "") return undefined;
    try {
      return JSON.parse(text);
    } catch (error) {
      return text;
    }
  }

  /* `uv add` for the core with the extras a document's plugins need, if any. */
  function addCore(extras, always) {
    var wanted = extras.filter(function (extra, i) {
      return extra && extras.indexOf(extra) === i;
    }).sort();
    if (wanted.length) return ['uv add "harnessweaver[' + wanted.join(",") + ']"'];
    return always ? ["uv add harnessweaver"] : [];
  }

  /* The extra for a model provider's plugin. */
  function providerExtra(provider) {
    return { "openai.chat": "openai", "anthropic.messages": "anthropic" }[provider] || "";
  }

  /* ---- Sections that several documents share ---- */

  /*
   * models, for a provider: scripted canned answers, or a provider with its own settings
   * next to it, the aliases and the fast model's price. An overlay leaves the default
   * alias, and any alias the reader didn't name, to the spec it changes.
   */
  function models(r, provider, overlay) {
    if (provider === "scripted") {
      return { provider: provider, replies: [{ text: r.text("reply") || "Hello." }] };
    }
    var fallback = overlay ? "" : MODELS[provider].fast;
    var fast = r.text("fast_model") || fallback;
    var prices = {};
    if (r.number("price_in") !== undefined && r.number("price_out") !== undefined) {
      prices[fast] = { input_per_mtok: r.number("price_in"), output_per_mtok: r.number("price_out") };
    }
    return {
      provider: provider,
      base_url: provider === "openai.chat" ? r.text("base_url") : undefined,
      api_key_env: provider === "openai.chat" ? r.text("api_key_env") : undefined,
      effort: provider === "anthropic.messages" ? r.text("effort") : undefined,
      default: overlay ? undefined : "fast",
      aliases: { fast: fast, strong: r.text("strong_model") },
      prices: prices,
    };
  }

  /*
   * guardrails: the guards ticked, by stage, each with an id (`prefix` and its short name),
   * so a later layer can change it, or a profile lock it. New guards start in shadow mode
   * (RULES R8), unless the reader asks to enforce them.
   */
  function guardrails(r, prefix) {
    var stages = {};
    GUARDS.forEach(function (offered) {
      if (!r.on(offered[0])) return;
      var guard = Object.assign({}, offered[2], { id: prefix + offered[2].id });
      if (guard.use === "topic.deny") {
        if (!r.list("topics").length) return;
        guard.topics = { denied: r.list("topics") };
      }
      if (guard.use === "size.limit") guard.max_chars = r.number("max_chars") || 4000;
      if (r.text("guard_mode") !== "enforce") guard.mode = "log_only";
      if (r.on("guard_sidecar")) guard.where = "sidecar";
      (stages[offered[1]] = stages[offered[1]] || []).push(guard);
    });
    return stages;
  }

  /* policy: what a call no rule matches gets, and one rule, with this id. */
  function policy(r, id) {
    return {
      default_effect: r.text("default_effect"),
      rules: r.text("rule_when") ? [{
        id: id,
        when: r.text("rule_when"),
        effect: r.text("rule_effect"),
        reason: r.text("rule_reason"),
      }] : [],
    };
  }

  /* validation: the repairs, what follows the last, and one business rule. */
  function validation(r) {
    return {
      max_repairs: r.number("max_repairs"),
      on_failure: r.text("on_failure"),
      rules: r.text("check_when") ? [{
        id: "app-check",
        when: r.text("check_when"),
        message: r.text("check_message") || "the output breaks a business rule",
      }] : [],
    };
  }

  /* The budget limits a form sets, for a task or for each run. */
  function budget(r) {
    return {
      max_model_calls: r.number("max_model_calls"),
      max_tool_calls: r.number("max_tool_calls"),
      max_usd: r.number("max_usd"),
      deadline: r.text("deadline"),
    };
  }

  /* approvals, state and observability, onto the spec. */
  function runtime(r, spec) {
    var channel = r.text("approvals");
    spec.approvals = {
      use: channel,
      url: channel === "webhook" ? r.text("webhook_url") : undefined,
      handler: channel === "callback" ? r.imports(r.text("callback_handler"), "function") : undefined,
      timeout: r.text("approval_timeout"),
    };
    spec.state = {
      use: r.text("state"),
      path: r.text("state") === "sqlite" ? r.text("state_path") : undefined,
      record: r.on("record") || undefined,
    };
    var exporter = r.text("exporter");
    // An exporter needs the harness to set up the OpenTelemetry SDK (RULES R5).
    spec.observability = exporter ? {
      configure_sdk: true,
      exporter: exporter,
      endpoint: exporter === "otlp" ? r.text("endpoint") : undefined,
      service_name: r.text("service_name"),
    } : {};
  }

  /* A document as the result buildSpec returns. */
  function result(file, document, r, install, check, use) {
    var header = [
      "# " + file + ", written by the HarnessWeaver spec generator.",
      "# Check it with: " + check.join(" && "),
    ];
    return {
      file: file,
      yaml: header.concat(lines(prune(document), "")).join("\n") + "\n",
      files: r.files,
      install: install,
      check: check,
      use: use,
    };
  }

  /* ---- The app spec ---- */

  /*
   * harness.yaml. The integration style decides its shape: a task the harness runs, a
   * session your code opens with no task, or a client or agent the app already has, which
   * the harness wraps. With no task, the budget is each run's (each call's, when wrapped).
   * In TypeScript, the app's code is always the session, which governs its own AI SDK
   * model; the model provider stays for Python, which runs the task in harnessd and loads
   * the spec in `spec validate`. Runners, approvals, state and telemetry are Python's and
   * are left out, as are evals, which Python runs.
   */
  function harnessSpec(r) {
    var ts = r.text("language") === "typescript";
    var style = r.text("style") || "task";
    if (ts && style === "wrap") style = "session";
    var task = style === "task";
    var wraps = style === "wrap" ? r.text("wraps") : "";
    var runner = task && !ts ? r.text("runner") : "";
    var name = r.text("task") || "main";
    // Your own code calls s.context, s.decide and s.memory: a session, or a task's
    // session or workflow runner, and always in TypeScript.
    var yourCode = ts || style === "session" || runner === "session" || runner === "workflow";
    var offersTools = task && (ts || runner === "direct" || runner === "pydantic_ai.agent");
    var provider = r.text("provider");

    var spec = {
      apiVersion: API_VERSION,
      kind: "Harness",
      metadata: { name: r.text("name"), owner: r.text("owner"), risk_tier: r.text("risk_tier") },
      extends: [r.text("baseline"), r.text("profile") === "none" ? "" : "profile://" + r.text("profile")],
    };

    spec.plugins = { local: ts || !r.text("plugin_local") ? [] : [r.text("plugin_local")] };
    // A client or agent the harness wraps calls its own model.
    if (!wraps) spec.models = models(r, provider, false);

    var routes = r.lines("router_options");
    if (yourCode && routes.length) {
      // One option a line, with its examples after a colon: the lexical stage picks the
      // option whose examples are closest to the text.
      var options = [];
      var utterances = {};
      routes.forEach(function (line) {
        var option = line.split(":")[0].trim();
        var examples = line.split(":").slice(1).join(":").split(",").map(function (example) {
          return example.trim();
        }).filter(Boolean);
        options.push(option);
        if (examples.length) utterances[option] = examples;
      });
      spec.routing = {};
      spec.routing[r.text("router") || "intent"] = {
        options: options,
        cascade: Object.keys(utterances).length ? [{ id: "examples", use: "lexical", utterances: utterances }] : [],
        default: r.text("router_default") || options[options.length - 1],
      };
    }

    if (yourCode && r.text("kb_file")) {
      r.need(r.text("kb_file"), "documents");
      spec.context = { kb: { use: "memory", file: r.text("kb_file"), max_items: 3 } };
    }
    if (yourCode && r.on("memory")) spec.memory = { use: "memory", default_ttl: r.text("memory_ttl") };

    spec.guardrails = guardrails(r, "");
    spec.validation = validation(r);

    var tools = offersTools ? r.list("tools") : [];
    tools.forEach(function (tool) { r.need("tools/" + tool + ".tool.yaml", "manifest", tool); });
    spec.tools = {
      manifests: tools.length ? ["tools/*.tool.yaml"] : [],
      approval_by_risk: r.on("approve_risky") ? { high: "required", critical: "required" } : {},
    };
    spec.policy = policy(r, "app-rule");
    if (!ts) runtime(r, spec);

    var middleware = r.list("middleware");
    if (middleware.length && spec.plugins.local.length) {
      // The in-repo plugin holds the middleware, in the namespace of the first one.
      var pluginFile = r.text("plugin_local").replace(/\./g, "/") + ".py";
      middleware.forEach(function (use) { r.need(pluginFile, "middleware", use); });
      r.need(pluginFile, "plugin", middleware[0].split(".")[0]);
    }
    spec.middleware = middleware.map(function (use) {
      return { id: use.split(".").slice(1).join(".") || use, use: use };
    });
    if (r.on("guard_sidecar")) spec.sidecar = { url: r.text("sidecar_url") };

    if (task) {
      var item = { version: "1.0.0" };
      if (runner === "session") {
        item.runner = { use: "session", handler: r.imports(r.text("handler"), "function") };
      } else if (runner === "workflow") {
        // Each step needs the one before it; a step's id is its function's name.
        var previous;
        item.runner = { use: "workflow", steps: r.list("steps").map(function (ref) {
          var step = { id: ref.split(":")[1].replace(/^[^A-Za-z]+/, ""), handler: r.imports(ref, "function") };
          if (previous) step.needs = [previous];
          previous = step.id;
          return step;
        }) };
      } else if (runner === "pydantic_ai.agent") {
        item.runner = { use: "pydantic_ai.agent", agent: r.imports(r.text("agent"), "agent") };
      } else if (runner) {
        item.runner = runner;
      }
      if (!ts && (runner === "direct" || runner === "pydantic_ai.agent") && r.text("prompt")) {
        r.need("prompts/" + r.text("prompt") + ".md", "prompt");
        item.prompt = r.text("prompt");
      }
      item.input = r.text("input") ? r.imports(r.text("input"), "model") : undefined;
      item.output = r.text("output") && r.text("output") !== "str" ? r.imports(r.text("output"), "model") : "str";
      item.tools = tools;
      item.budget = budget(r);
      spec.tasks = {};
      spec.tasks[name] = item;
      // Evals run tasks, in Python.
      if (!ts && r.on("evals")) {
        r.need("evals/golden.yaml", "dataset", name);
        spec.evals = {};
        spec.evals[name] = ["evals/golden.yaml"];
      }
    } else {
      spec.budgets = { per_run: budget(r) };
    }

    var install;
    if (ts) {
      // The CLI checks the spec in Python, with the plugin of its model provider.
      var extra = providerExtra(provider);
      install = [
        "npm install @harnessweaver/core @harnessweaver/ai-sdk ai @ai-sdk/provider",
        "uv tool install harnessweaver-cli" + (extra ? ' --with "harnessweaver[' + extra + ']"' : ""),
      ];
    } else {
      install = addCore([
        spec.models ? providerExtra(spec.models.provider) : "",
        spec.observability.exporter ? "otel" : "",
        runner === "pydantic_ai.agent" ? "pydantic-ai" : "",
        { openai: "openai", anthropic: "anthropic", pydantic_ai: "pydantic-ai" }[wraps] || "",
      ], true).concat(["uv add --dev harnessweaver-cli"]);
    }
    if (r.on("guard_sidecar")) install.push("uv tool install harnessweaver-sidecar");
    if (middleware.length && !spec.plugins.local.length) {
      install.push("uv add <the package of the plugin " + middleware[0].split(".")[0] + ">");
    }

    return result("harness.yaml", spec, r, install, ["harnessweaver spec validate harness.yaml"],
      harnessUse(ts, style, wraps, name));
  }

  /* How the app's code uses its spec, by language and integration style. */
  function harnessUse(ts, style, wraps, name) {
    var quoted = JSON.stringify(name);
    if (ts) {
      return [
        'import { load } from "@harnessweaver/core";',
        'import { wrapModel } from "@harnessweaver/ai-sdk";',
        "",
        'const harness = load("harness.yaml");',
        "const answer = await harness.session(",
        "  { " + (style === "task" ? "task: " + quoted + ", " : "") + "principal: user.id },",
        '  async (s) => (await generateText({ model: wrapModel(s, model, { alias: "fast" }), prompt })).text,',
        ");",
      ].join("\n");
    }
    var load = ["import harnessweaver as hw", "", 'harness = hw.load("harness.yaml")'];
    var body = {
      task: ["result = await harness.run(" + quoted + ", request, principal=user)"],
      session: [
        "async with harness.session(principal=user) as s:",
        '    question = await s.guard("input", question)',
        '    answer = await s.generate(messages=[{"role": "user", "content": question}])',
      ],
      openai: ["client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))"],
      anthropic: ["client = harness.instrument(AsyncAnthropic())"],
      pydantic_ai: ["agent = harness.wrap(agent)"],
    }[style === "wrap" ? wraps : style];
    return load.concat(body).join("\n");
  }

  /* ---- The profile ---- */

  /*
   * A profile: an org baseline the platform team publishes, a profile the app's own team
   * shares between its apps, or one a plugin ships. Its guards and rule get ids that start
   * with its name, so they don't collide with an app's, and are locked by those ids. Locks
   * stop later layers changing a value (RULES R1); bounds keep numbers in range (R10).
   */
  function profileSpec(r) {
    var name = r.text("name");
    var spec = {
      apiVersion: API_VERSION,
      kind: "Profile",
      metadata: { name: name, version: r.text("version"), owner: r.text("owner"), description: r.text("description") },
      extends: r.list("extends"),
    };
    var locks = [];
    function lock(key, path, value) {
      if (r.on(key) && present(prune(value))) locks.push(path);
    }

    // A plugin's profile is loaded from its plugin, which its allow-list must therefore name.
    var where = r.text("profile_kind");
    var allow = r.list("allow");
    if (where === "plugin" && allow.length && allow.indexOf(r.text("plugin_ns")) < 0) {
      allow.push(r.text("plugin_ns"));
    }
    spec.plugins = { allow: allow };
    lock("lock_allow", "plugins.allow", spec.plugins.allow);

    var gateway = r.text("provider");
    spec.models = gateway ? models(r, gateway, false) : {};
    spec.models.allowed_aliases = r.list("allowed_aliases");
    if (gateway) {
      lock("lock_gateway", "models.provider", gateway);
      lock("lock_gateway", "models.base_url", spec.models.base_url);
    }

    spec.guardrails = guardrails(r, name + "-");
    Object.keys(spec.guardrails).forEach(function (stage) {
      spec.guardrails[stage].forEach(function (guard) {
        lock("lock_guards", "guardrails." + stage + "[" + guard.id + "]", guard);
      });
    });
    spec.validation = { max_repairs: r.number("max_repairs"), on_failure: r.text("on_failure") };

    spec.tools = {
      require_manifest: r.on("lock_manifest") || undefined,
      trifecta: r.text("trifecta"),
      approval_by_risk: r.on("approve_risky") ? { high: "required", critical: "required" } : {},
    };
    lock("lock_manifest", "tools.require_manifest", spec.tools.require_manifest);
    lock("lock_risk", "tools.approval_by_risk", spec.tools.approval_by_risk);

    spec.policy = policy(r, name + "-rule");
    lock("lock_rule", "policy.rules[" + name + "-rule]", spec.policy.rules);

    spec.budgets = { per_run: budget(r) };
    // capture_content is already false (RULES R9); the profile restates it to lock it.
    spec.observability = { capture_content: r.on("lock_capture") ? false : undefined };
    lock("lock_capture", "observability.capture_content", "false");

    var tiers = {};
    ["internal", "customer_facing", "takes_actions"].forEach(function (tier) {
      tiers[tier] = r.text("level_" + tier);
    });
    var level = r.text("level_default");
    spec.require_level = { default: level === "L0" ? undefined : level, tiers: tiers };

    spec.locks = locks.concat(r.list("locks"));
    spec.bounds = {};
    [
      ["bound_run_usd", "budgets.per_run.max_usd"],
      ["bound_run_deadline", "budgets.per_run.deadline"],
      ["bound_task_usd", "tasks.*.budget.max_usd"],
      ["bound_task_tool_calls", "tasks.*.budget.max_tool_calls"],
      ["bound_repairs", "validation.max_repairs"],
    ].forEach(function (bound) {
      var value = r.number(bound[0]) === undefined ? r.text(bound[0]) : r.number(bound[0]);
      if (present(value)) spec.bounds[bound[1]] = { max: value };
    });

    // Apps pin a range: the same major version, or the same minor one below 1.0.
    var version = r.text("version") || "1.0.0";
    var range = "^" + (version.split(".")[0] === "0" ? version : version.split(".")[0]);
    var file = (where === "team" ? ".harness/profiles/" : "profiles/") + name + ".yaml";
    var ref = where === "plugin" ? "profile://" + r.text("plugin_ns") + "." + name : "org://" + name;
    var use = [];
    if (where === "plugin") {
      use.push("# In the plugin package, next to its __init__.py:");
      use.push("plugin = hw.Plugin(namespace=" + JSON.stringify(r.text("plugin_ns")) +
        ", ..., profiles={" + JSON.stringify(name) + ": " + JSON.stringify(file) + "})");
      use.push("");
    }
    use.push("# In each app's harness.yaml:");
    use.push("extends: [" + JSON.stringify(ref + "@" + range) + "]");
    var check = "harnessweaver spec validate harness.yaml" + (where === "org" ? " --profile-dir profiles" : "");
    return result(file, spec, r, [], [check], use.join("\n"));
  }

  /* ---- The environment overlay ---- */

  /*
   * harness.<env>.yaml: sections only, merged over harness.yaml when HARNESSWEAVER_ENV
   * names the environment. Usually a scripted model for tests and demos, or the gateway,
   * model names, telemetry, state and approvals of a deployment.
   */
  function overlaySpec(r) {
    var env = r.text("env") || "offline";
    var provider = r.text("provider");
    var spec = { apiVersion: API_VERSION, kind: "Overlay" };
    spec.models = provider ? models(r, provider, true) : {};
    runtime(r, spec);
    spec.sidecar = { url: r.text("sidecar_url") };
    var install = addCore([providerExtra(provider), spec.observability.exporter ? "otel" : ""], false);
    return result("harness." + env + ".yaml", spec, r, install,
      ["harnessweaver spec validate harness.yaml -e " + env],
      "HARNESSWEAVER_ENV=" + env + " uv run python app.py\n# or, in code: hw.load(\"harness.yaml\", env=" +
        JSON.stringify(env) + ")");
  }

  /* ---- The tool manifest ---- */

  /*
   * A tool's manifest (RULES S2): how it is reached, its arguments, what it may touch,
   * and when a person must approve a call. `tools pin` then writes the digest that pins
   * its definition, so a tool changed without review can't run.
   */
  function toolSpec(r) {
    var name = r.text("name");
    var transport = r.text("transport");
    var properties = {};
    var required = [];
    // One argument a line, `name: type`, with "?" after an optional one's name.
    r.lines("arguments").forEach(function (line) {
      var arg = line.split(":")[0].trim();
      var optional = arg.endsWith("?");
      arg = arg.replace(/\?$/, "").trim();
      properties[arg] = { type: line.split(":").slice(1).join(":").trim() || "string" };
      if (!optional) required.push(arg);
    });
    var headers = {};
    r.list("headers_env").forEach(function (item) {
      headers[item.split("=")[0].trim()] = item.split("=").slice(1).join("=").trim();
    });
    var spec = {
      apiVersion: API_VERSION,
      kind: "Tool",
      metadata: { name: name, version: r.text("version"), owner: r.text("owner") },
      spec: {
        transport: transport,
        handler: transport === "native" ? r.imports(r.text("handler") || "app.tools:" + name, "function") : undefined,
        url: transport === "http" ? r.text("url") : undefined,
        headers_env: transport === "http" ? headers : {},
        sandbox: transport === "code" ? "monty" : undefined,
        code_arg: transport === "code" && r.text("code_arg") !== "code" ? r.text("code_arg") : undefined,
        description: r.text("description"),
        input_schema: { type: "object", properties: properties, required: required },
        timeout: r.text("timeout"),
        side_effect: r.text("side_effect"),
        risk: r.text("risk"),
        data_access: r.list("data_access"),
        egress: r.list("egress"),
        scopes: r.list("scopes"),
        tenants: r.list("tenants"),
        rate_limit: { per_principal: r.text("rate_principal"), per_tenant: r.text("rate_tenant") },
        approval: r.text("approval_when") ? {
          when: r.text("approval_when"),
          approver_role: r.text("approver_role"),
        } : {},
        output: {
          max_bytes: r.number("max_bytes"),
          sanitize: [r.on("sanitize_pii") ? "pii_redact" : "", r.on("sanitize_instructions") ? "strip_instructions" : ""],
          label: r.text("label") === "trusted" ? "trusted" : undefined,
        },
      },
    };
    return result("tools/" + name + ".tool.yaml", spec, r, addCore([transport === "code" ? "monty" : ""], false),
      ["harnessweaver tools pin harness.yaml", "harnessweaver doctor harness.yaml"],
      ["# In harness.yaml:", "tools:", '  manifests: ["tools/*.tool.yaml"]', "tasks:", "  support:",
        "    tools: [" + name + "]"].join("\n"));
  }

  /* ---- The eval suite ---- */

  /*
   * An eval dataset: the graders every case gets, the share of cases that must pass, and
   * a first case. A case's input and expected output are JSON values when they parse as
   * JSON, else text.
   */
  function evalSpec(r) {
    var suite = r.text("suite") || "golden";
    var graders = [r.on("grade_schema") ? "schema_valid" : "", r.on("grade_exact") ? "exact" : ""];
    r.list("field_equals").forEach(function (field) { graders.push({ field_equals: field }); });
    var contains = r.list("contains");
    if (contains.length) graders.push({ contains: contains.length === 1 ? contains[0] : contains });
    if (r.text("status")) graders.push({ status: r.text("status") });
    var fired = r.list("guard_fired");
    if (fired.length) graders.push({ guard_fired: fired.length === 1 ? fired[0] : fired });
    if (r.text("rubric")) graders.push({ llm_judge: r.text("rubric") });
    var spec = {
      suite: suite,
      task: r.text("task"),
      graders: graders,
      thresholds: { pass_rate: r.number("pass_rate") },
      cases: [{
        id: r.text("case_id") || "first",
        input: typed(r.text("case_input")),
        expect: typed(r.text("case_expect")),
      }],
    };
    var file = "evals/" + suite + ".yaml";
    return result(file, spec, r, [], ["harnessweaver eval run harness.yaml -e offline"],
      ["# In harness.yaml:", "evals:", "  " + scalar(r.text("task")) + ": [" + file + "]"].join("\n"));
  }

  var WRITERS = { harness: harnessSpec, profile: profileSpec, overlay: overlaySpec, tool: toolSpec, eval: evalSpec };

  /* The document for one form's values; `doc` picks it, and an app spec is the default. */
  function buildSpec(values) {
    return WRITERS[values.doc || "harness"](reader(values));
  }

  var api = { buildSpec: buildSpec, MODELS: MODELS };
  if (typeof module !== "undefined" && module.exports) {
    // Node.js, for the tests in docs_src/tests.
    module.exports = api;
  } else {
    globalThis.hwSpecGenerator = api;
  }
})();
