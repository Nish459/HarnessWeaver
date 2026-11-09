/*
 * The spec generator (docs/learn/spec-generator.md): writes a harness.yaml from the
 * choices in the page's form, as the reader makes them.
 *
 * buildSpec turns the form's values (what FormData gives: strings, and "on" for a checked
 * box) into the spec, as a plain object, then into YAML. It also lists the files the spec
 * refers to, which `harnessweaver spec validate` needs to find, and the install commands
 * for the plugins it uses. It touches no page, so docs_src/tests runs it under Node.js and
 * checks that each spec it writes loads. Everything runs in the browser: nothing typed
 * into the form leaves the page.
 */

(function () {
  "use strict";

  /* What each model provider's aliases default to. */
  var MODELS = {
    "openai.chat": { fast: "your-fast-model", strong: "" },
    "anthropic.messages": { fast: "claude-haiku-5-5", strong: "claude-opus-5-5" },
    scripted: { fast: "", strong: "" },
  };

  /* The guards the form offers: its checkbox, the stage, and the guard. */
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
   * maps and its lists of maps go on the lines below their key; a list of scalars stays
   * on the key's line, as [a, b]. A list item that is a map starts with "- " and its
   * other keys line up under its first.
   */
  function lines(value, indent) {
    var out = [];
    if (Array.isArray(value)) {
      value.forEach(function (item) {
        var inner = lines(item, indent + "  ");
        out.push(indent + "- " + inner[0].slice(indent.length + 2));
        out.push.apply(out, inner.slice(1));
      });
      return out;
    }
    Object.keys(value).forEach(function (key) {
      var item = value[key];
      var nested = isObject(item) || (Array.isArray(item) && item.some(isObject));
      if (nested) {
        out.push(indent + scalar(key) + ":");
        out.push.apply(out, lines(item, indent + "  "));
      } else if (Array.isArray(item)) {
        out.push(indent + scalar(key) + ": [" + item.map(flowScalar).join(", ") + "]");
      } else {
        out.push(indent + scalar(key) + ": " + scalar(item));
      }
    });
    return out;
  }

  /* A spec, as the YAML text of a harness.yaml. */
  function toYaml(spec) {
    return [
      "# harness.yaml, written by the HarnessWeaver spec generator.",
      "# Check it with: harnessweaver spec validate harness.yaml",
    ].concat(lines(spec, "")).join("\n") + "\n";
  }

  /*
   * The spec for a set of form values, with the files it refers to and the commands that
   * install what it uses.
   *
   * Returns {yaml, files, install}. Each file is {path, kind, name}: kind says what goes
   * in it (a prompt, a Pydantic model, a function, a Pydantic AI agent, a tool manifest,
   * the documents to retrieve from, or an eval dataset), and name the attribute a spec
   * imports from it, or the tool a manifest describes.
   */
  function buildSpec(values) {
    function text(key) {
      return String(values[key] || "").trim();
    }
    function list(key) {
      return text(key).split(",").map(function (item) { return item.trim(); }).filter(Boolean);
    }
    function number(key) {
      return text(key) === "" || isNaN(Number(text(key))) ? undefined : Number(text(key));
    }
    function on(key) {
      return values[key] === "on";
    }

    var files = [];
    function need(path, kind, name) {
      var file = name ? { path: path, kind: kind, name: name } : { path: path, kind: kind };
      var known = files.some(function (f) { return f.path === path && f.name === file.name; });
      if (!known) files.push(file);
    }
    /* An import path, package.module:attribute, is a file next to the spec. */
    function imports(ref, kind) {
      var parts = ref.split(":");
      need(parts[0].replace(/\./g, "/") + ".py", kind, parts[1]);
      return ref;
    }

    var provider = text("provider");
    var runner = text("runner");
    var name = text("task") || "main";
    var spec = {
      apiVersion: "harnessweaver/v1",
      kind: "Harness",
      metadata: { name: text("name"), owner: text("owner"), risk_tier: text("risk_tier") },
      extends: [text("baseline"), text("profile") === "none" ? "" : "profile://" + text("profile")],
    };

    if (provider === "scripted") {
      spec.models = { provider: provider, replies: [{ text: text("reply") || "Hello." }] };
    } else {
      spec.models = {
        provider: provider,
        base_url: provider === "openai.chat" ? text("base_url") : undefined,
        api_key_env: provider === "openai.chat" ? text("api_key_env") : undefined,
        effort: provider === "anthropic.messages" ? text("effort") : undefined,
        default: "fast",
        aliases: { fast: text("fast_model") || MODELS[provider].fast, strong: text("strong_model") },
      };
    }

    // Retrieval is for code that fetches, so only your own steps get a knowledge base.
    if (text("kb_file") && (runner === "session" || runner === "workflow")) {
      need(text("kb_file"), "documents");
      spec.context = { kb: { use: "memory", file: text("kb_file"), max_items: 3 } };
    }

    // New guards start in shadow mode (RULES R8), unless the reader asks to enforce them.
    spec.guardrails = {};
    GUARDS.forEach(function (offered) {
      if (!on(offered[0])) return;
      var guard = Object.assign({}, offered[2]);
      if (guard.use === "topic.deny") {
        if (!list("topics").length) return;
        guard.topics = { denied: list("topics") };
      }
      if (guard.use === "size.limit") guard.max_chars = number("max_chars") || 4000;
      if (text("guard_mode") !== "enforce") guard.mode = "log_only";
      (spec.guardrails[offered[1]] = spec.guardrails[offered[1]] || []).push(guard);
    });

    spec.validation = {
      max_repairs: number("max_repairs"),
      on_failure: text("on_failure"),
      rules: text("check_when") ? [{
        id: "app-check",
        when: text("check_when"),
        message: text("check_message") || "the output breaks a business rule",
      }] : [],
    };

    var offersTools = runner === "direct" || runner === "pydantic_ai.agent";
    var tools = offersTools ? list("tools") : [];
    tools.forEach(function (tool) { need("tools/" + tool + ".tool.yaml", "manifest", tool); });
    spec.tools = {
      manifests: tools.length ? ["tools/*.tool.yaml"] : [],
      approval_by_risk: on("approve_risky") ? { high: "required", critical: "required" } : {},
    };

    spec.policy = {
      default_effect: text("default_effect"),
      rules: text("rule_when") ? [{
        id: "app-rule",
        when: text("rule_when"),
        effect: text("rule_effect"),
        reason: text("rule_reason"),
      }] : [],
    };

    var channel = text("approvals");
    spec.approvals = {
      use: channel,
      url: channel === "webhook" ? text("webhook_url") : undefined,
      handler: channel === "callback" ? imports(text("callback_handler"), "function") : undefined,
      timeout: text("approval_timeout"),
    };

    spec.state = {
      use: text("state"),
      path: text("state") === "sqlite" ? text("state_path") : undefined,
      record: on("record") || undefined,
    };

    var exporter = text("exporter");
    spec.observability = exporter ? {
      configure_sdk: true,
      exporter: exporter,
      endpoint: exporter === "otlp" ? text("endpoint") : undefined,
    } : {};

    var task = { version: "1.0.0" };
    if (runner === "session") {
      task.runner = { use: "session", handler: imports(text("handler"), "function") };
    } else if (runner === "workflow") {
      // Each step needs the one before it; a step's id is its function's name.
      var previous;
      task.runner = { use: "workflow", steps: list("steps").map(function (ref) {
        var step = { id: ref.split(":")[1].replace(/^[^A-Za-z]+/, ""), handler: imports(ref, "function") };
        if (previous) step.needs = [previous];
        previous = step.id;
        return step;
      }) };
    } else if (runner === "pydantic_ai.agent") {
      task.runner = { use: "pydantic_ai.agent", agent: imports(text("agent"), "agent") };
    } else {
      task.runner = "direct";
    }
    if (offersTools && text("prompt")) {
      need("prompts/" + text("prompt") + ".md", "prompt");
      task.prompt = text("prompt");
    }
    task.input = text("input") ? imports(text("input"), "model") : undefined;
    task.output = text("output") && text("output") !== "str" ? imports(text("output"), "model") : "str";
    task.tools = tools;
    task.budget = {
      max_model_calls: number("max_model_calls"),
      max_tool_calls: number("max_tool_calls"),
      max_usd: number("max_usd"),
      deadline: text("deadline"),
    };
    spec.tasks = {};
    spec.tasks[name] = task;

    if (on("evals")) {
      need("evals/golden.yaml", "dataset");
      spec.evals = {};
      spec.evals[name] = ["evals/golden.yaml"];
    }

    var extras = [
      provider === "openai.chat" ? "openai" : "",
      provider === "anthropic.messages" ? "anthropic" : "",
      exporter ? "otel" : "",
      runner === "pydantic_ai.agent" ? "pydantic-ai" : "",
    ].filter(Boolean).sort();
    return {
      yaml: toYaml(prune(spec)),
      files: files,
      install: [
        extras.length ? 'uv add "harnessweaver[' + extras.join(",") + ']"' : "uv add harnessweaver",
        "uv add --dev harnessweaver-cli",
      ],
    };
  }

  /* What each kind of file holds, for the page's list. */
  var KINDS = {
    prompt: function () { return "the task's prompt"; },
    model: function (name) { return "the Pydantic model " + name; },
    function: function (name) { return "the function " + name; },
    agent: function (name) { return "the Pydantic AI agent " + name; },
    manifest: function (name) { return "the manifest of the tool " + name; },
    documents: function () { return "the documents to retrieve from"; },
    dataset: function () { return "the eval cases, which eval run reads"; },
  };

  /* Wire the form to the spec beside it, if this page has the generator. */
  function setUp() {
    var form = document.getElementById("hw-gen-form");
    if (!form) return;
    var output = document.getElementById("hw-gen-yaml");
    var install = document.getElementById("hw-gen-install");
    var fileList = document.getElementById("hw-gen-files");
    var provider = form.elements.provider.value;

    function valueOf(field) {
      var element = form.elements[field];
      return element.type === "checkbox" ? (element.checked ? "on" : "") : element.value;
    }

    function render() {
      // A new provider's model defaults replace the last one's, unless the reader typed others.
      var chosen = form.elements.provider.value;
      if (chosen !== provider) {
        ["fast", "strong"].forEach(function (alias) {
          var input = form.elements[alias + "_model"];
          if (input.value === MODELS[provider][alias]) input.value = MODELS[chosen][alias];
        });
        provider = chosen;
      }
      // data-when="field=a|b" shows a part of the form only for those values of the field.
      form.querySelectorAll("[data-when]").forEach(function (part) {
        var rule = part.getAttribute("data-when").split("=");
        part.hidden = rule[1].split("|").indexOf(valueOf(rule[0])) < 0;
      });

      var result = buildSpec(Object.fromEntries(new FormData(form)));
      output.textContent = result.yaml;
      install.textContent = result.install.join("\n");
      var byPath = {};
      result.files.forEach(function (file) {
        (byPath[file.path] = byPath[file.path] || []).push(KINDS[file.kind](file.name));
      });
      fileList.replaceChildren.apply(fileList, Object.keys(byPath).map(function (path) {
        var item = document.createElement("li");
        var code = document.createElement("code");
        code.textContent = path;
        item.append(code, ": " + byPath[path].join(", "));
        return item;
      }));
      fileList.parentElement.hidden = result.files.length === 0;
    }

    form.addEventListener("input", render);
    form.addEventListener("change", render);
    // The reset event comes before the form's values are reset.
    form.addEventListener("reset", function () { setTimeout(render); });

    document.getElementById("hw-gen-copy").addEventListener("click", function (event) {
      var button = event.currentTarget;
      navigator.clipboard.writeText(output.textContent).then(function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy"; }, 1500);
      });
    });
    document.getElementById("hw-gen-download").addEventListener("click", function () {
      var link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([output.textContent], { type: "application/yaml" }));
      link.download = "harness.yaml";
      link.click();
      URL.revokeObjectURL(link.href);
    });
    render();
  }

  if (typeof module !== "undefined" && module.exports) {
    // Node.js, for the tests in docs_src/tests.
    module.exports = { buildSpec: buildSpec, toYaml: toYaml };
  } else if (typeof document$ !== "undefined") {
    // Material's document$ fires on every page load, including instant navigation.
    document$.subscribe(setUp);
  } else {
    document.addEventListener("DOMContentLoaded", setUp);
  }
})();
