"""The spec generator page writes documents that load (docs/javascripts/spec-generator.js).

The page has one form for each document it writes: an app spec, a profile, an environment
overlay, a tool manifest and an eval suite. The writer, ``buildSpec``, runs under Node.js on
sets of choices, laid over the defaults of that document's form on the page. For each
document, the test creates a stub of every file the page tells the reader to create, then
checks the document with the commands the page gives: ``spec validate`` for an app spec and
an overlay, an app that extends a profile, an app that uses a tool, and ``eval run`` for an
eval suite. Each must pass: that is what the page promises a reader who follows it.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "docs" / "javascripts" / "spec-generator.js"
# The TypeScript core, as `pnpm -C typescript build` leaves it.
TS_CORE = ROOT / "typescript" / "packages" / "core" / "dist" / "index.js"
PAGE = ROOT / "docs" / "learn" / "spec-generator.md"
CLI = Path(sys.executable).parent / "harnessweaver"

# Reads the JSON list of form values on stdin and prints buildSpec's result for each.
RUN = """
const { buildSpec } = require(process.argv[1]);
const cases = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(buildSpec)));
"""


class FormDefaults(HTMLParser):
    """The values each of the page's forms submits before the reader changes anything, as
    the browser's ``FormData`` reports them: a checked box is ``on``, a select its selected
    option, or else its first, and a text area its text. Forms are keyed by ``data-doc``."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: dict[str, dict[str, str]] = {}
        self._form: dict[str, str] | None = None
        self._select: str | None = None
        self._picked = False
        self._textarea: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter a form, or record a field's value in the form it is in."""
        a = {key: value or "" for key, value in attrs}
        if tag == "form" and "data-doc" in a:
            self._form = self.forms.setdefault(a["data-doc"], {})
        values = self._form
        if values is None:
            return
        if tag == "input" and "name" in a:
            if a.get("type") != "checkbox":
                values[a["name"]] = a.get("value", "")
            elif "checked" in a:
                values[a["name"]] = "on"
        elif tag == "textarea":
            self._textarea = a["name"]
            values[a["name"]] = ""
        elif tag == "select":
            self._select, self._picked = a["name"], False
        elif tag == "option" and self._select is not None and not self._picked:
            if self._select not in values or "selected" in a:
                values[self._select] = a.get("value", "")
            self._picked = "selected" in a

    def handle_data(self, data: str) -> None:
        """Collect a text area's text."""
        if self._form is not None and self._textarea is not None:
            self._form[self._textarea] += data

    def handle_endtag(self, tag: str) -> None:
        """Leave a select, a text area or a form."""
        if tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None
        elif tag == "form":
            self._form = None


def page_defaults() -> dict[str, dict[str, str]]:
    """Each of the page's forms' default values, by the document it writes."""
    parser = FormDefaults()
    parser.feed(PAGE.read_text())
    return parser.forms


def generate(*choices: dict[str, str]) -> list[dict[str, Any]]:
    """Run buildSpec on each set of choices, laid over the defaults of its document's form
    (``doc``, the app spec's when there is none).

    Returns:
        Each result: the ``file`` to save it as, its ``yaml``, the ``files`` it refers to,
        and the commands to ``install`` what it uses and to ``check`` it, and how to ``use`` it.
    """
    node = shutil.which("node")
    assert node, "the spec generator's tests run it with Node.js 22 or later (AGENTS.md)"
    forms = page_defaults()
    cases = [forms[chosen.get("doc", "harness")] | chosen for chosen in choices]
    done = subprocess.run(
        [node, "-e", RUN, str(GENERATOR)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


# Stubs for each kind of file a document refers to: enough for it to load.
MANIFEST = """apiVersion: harnessweaver/v1
kind: Tool
metadata: {{ name: {name} }}
spec: {{ transport: native, handler: "app.tools:{name}" }}
"""
STUBS = {
    "prompt": "Answer the customer's question.\n",
    "model": "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    text: str = ''\n",
    "function": "\n\nasync def {name}(*args, **kwargs):\n    return ''\n",
    "agent": "from pydantic_ai import Agent\n\n{name} = Agent()\n",
    "documents": "documents: []\n",
    "dataset": "cases: []\n",
    "middleware": (
        "import harnessweaver as hw\n\n\n"
        '@hw.middleware(hooks=["input.before"], fail_mode="closed")\n'
        "async def {name}(event, env):\n    return None\n"
    ),
}


def create_files(folder: Path, files: list[dict[str, str]]) -> None:
    """Write a stub of every file the page lists, appending what shares a file. A plugin's
    module gets its middleware first, then the ``plugin`` object that lists them."""
    plugins = {f["path"]: (f["name"], list[str]()) for f in files if f["kind"] == "plugin"}
    for item in files:
        if item["kind"] == "plugin":
            continue
        if item["kind"] == "manifest":
            # The manifest names the tool's handler, which the stub puts in app/tools.py.
            (folder / "tools").mkdir(exist_ok=True)
            (folder / item["path"]).write_text(MANIFEST.format(name=item["name"]))
            item = {"path": "app/tools.py", "kind": "function", "name": item["name"]}
        name = item.get("name", "")
        if item["kind"] == "middleware":
            plugins[item["path"]][1].append(name.rpartition(".")[2])
            name = name.rpartition(".")[2]
        path = folder / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stub:
            stub.write(STUBS[item["kind"]].format(name=name))
    for path, (namespace, middleware) in plugins.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        with (folder / path).open("a") as stub:
            stub.write(
                f"\n\nimport harnessweaver as hw\n\nplugin = hw.Plugin(namespace={namespace!r}, "
                f"version='0.1.0', middleware=[{', '.join(middleware)}])\n"
            )


def write(folder: Path, result: dict[str, Any]) -> None:
    """Save a document where the page says to, with stubs of the files it refers to."""
    create_files(folder, result["files"])
    path = folder / result["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result["yaml"])


def check(folder: Path, result: dict[str, Any]) -> None:
    """Run each command the page gives to check a document, which must pass."""
    env = {**os.environ, "HARNESSWEAVER_TEST_MODE": "1"}
    for command in result["check"]:
        program, *args = shlex.split(command)
        assert program == "harnessweaver", command
        done = subprocess.run([CLI, *args], cwd=folder, env=env, capture_output=True, text=True)
        assert done.returncode == 0, (result["yaml"], command, done.stdout, done.stderr)


def write_app(folder: Path, app: dict[str, Any], **changes: Any) -> None:
    """Save an app spec, with its files, and with top-level ``changes`` to its document
    (``None`` removes a section)."""
    create_files(folder, app["files"])
    spec = yaml.safe_load(app["yaml"]) | changes
    spec = {key: value for key, value in spec.items() if value is not None}
    # JSON is YAML, and every reader reads it the same way.
    (folder / "harness.yaml").write_text(json.dumps(spec))


APPS = {
    "the page's defaults": {},
    "typed tools with every control": {
        "profile": "rag",
        "provider": "anthropic.messages",
        "fast_model": "claude-haiku-5-5",
        "strong_model": "claude-opus-5-5",
        "effort": "high",
        "price_in": "1",
        "price_out": "5",
        "input": "app.models:Ticket",
        "output": "app.models:Triage",
        "tools": "lookup_order, refund_payment",
        "approve_risky": "on",
        "max_tool_calls": "5",
        "deadline": "45s",
        "guard_pii": "on",
        "guard_injection": "on",
        "guard_topics": "on",
        "topics": "lawsuit, diagnosis",
        "guard_size": "on",
        "max_chars": "2000",
        "guard_secrets": "on",
        "guard_citations": "on",
        "guard_stream": "on",
        "guard_tool_secrets": "on",
        "guard_mode": "enforce",
        "default_effect": "require_approval",
        "rule_when": "tool.name == 'refund_payment' && args.amount_usd > 500",
        "rule_effect": "deny",
        "rule_reason": "Refunds over 500 USD go to finance.",
        "on_failure": "escalate",
        "max_repairs": "2",
        "check_when": "output.text == ''",
        "check_message": "write an answer",
        "approvals": "webhook",
        "approval_timeout": "4h",
        "state": "sqlite",
        "record": "on",
        "exporter": "otlp",
        "service_name": "support-desk",
    },
    "your own steps, offline": {
        "profile": "none",
        "provider": "scripted",
        "runner": "session",
        "kb_file": "data/kb.yaml",
        "router_options": "billing: refund my order, I was charged twice\nother",
        "memory": "on",
        "memory_ttl": "30d",
        "approvals": "callback",
        "exporter": "console",
        "evals": "",
    },
    "a workflow": {
        "profile": "workflow",
        "runner": "workflow",
        "steps": "app.steps:clean, app.steps:classify, app.steps:reply",
        "kb_file": "data/kb.yaml",
        "state": "",
        "record": "on",
    },
    "a Pydantic AI agent": {
        "profile": "agent",
        "risk_tier": "takes_actions",
        "runner": "pydantic_ai.agent",
        "tools": "lookup_order",
        "approvals": "console",
    },
    "a wrapped OpenAI client": {"style": "wrap", "wraps": "openai", "max_usd": "0.02"},
    "a wrapped Pydantic AI agent": {"style": "wrap", "wraps": "pydantic_ai"},
    "a session with no task": {
        "style": "session",
        "provider": "anthropic.messages",
        "fast_model": "claude-haiku-5-5",
        "kb_file": "data/kb.yaml",
        "router": "topic",
        "router_options": "orders: where is my order\nbilling: refund\nother",
        "router_default": "other",
        "memory": "on",
    },
    "TypeScript": {
        "language": "typescript",
        "tools": "lookup_order",
        "kb_file": "data/kb.yaml",
        "router_options": "billing: refund my order\nother",
        "price_in": "0.15",
        "price_out": "0.6",
        "guard_pii": "on",
        "exporter": "otlp",
    },
    "TypeScript, with no task": {
        "language": "typescript",
        "style": "session",
        "kb_file": "data/kb.yaml",
        "router_options": "billing: refund my order\nother",
        "guard_pii": "on",
    },
    "plugins and guards in harnessd": {
        "plugin_local": "app.harness_plugin",
        "middleware": "acme.no_weekend_refunds, acme.audit",
        "guard_pii": "on",
        "guard_secrets": "on",
        "guard_sidecar": "on",
        "sidecar_url": "http://127.0.0.1:7070",
    },
}

PROFILES = {
    "the page's defaults": {"doc": "profile"},
    "a team profile with every control": {
        "doc": "profile",
        "profile_kind": "team",
        "name": "support-defaults",
        "version": "0.3.0",
        "description": "What every support app shares.",
        "extends": "profile://rag",
        "provider": "openai.chat",
        "base_url": "https://llm-gateway.internal.example",
        "api_key_env": "LITELLM_API_KEY",
        "fast_model": "fast-chat",
        "lock_gateway": "on",
        "allowed_aliases": "fast",
        "guard_injection": "on",
        "guard_topics": "on",
        "topics": "lawsuit",
        "guard_size": "on",
        "max_chars": "8000",
        "guard_tool_secrets": "on",
        "guard_citations": "on",
        "guard_stream": "on",
        "guard_mode": "enforce",
        "trifecta": "block",
        "default_effect": "require_approval",
        "rule_when": "tool.name == 'refund_payment' && args.amount_usd > 500",
        "rule_effect": "deny",
        "rule_reason": "Big refunds go to finance.",
        "lock_rule": "on",
        "max_repairs": "2",
        "on_failure": "escalate",
        "max_model_calls": "10",
        "max_tool_calls": "20",
        "bound_task_tool_calls": "20",
        "bound_repairs": "3",
        "level_internal": "L2",
        "locks": "state.use",
    },
    "a plugin's profile": {
        "doc": "profile",
        "profile_kind": "plugin",
        "plugin_ns": "acme",
        "name": "baseline",
        "lock_allow": "",
        "approve_risky": "",
    },
}

OVERLAYS = {
    "the page's defaults": {"doc": "overlay"},
    "production": {
        "doc": "overlay",
        "env": "prod",
        "provider": "openai.chat",
        "base_url": "https://llm-gateway.internal.example",
        "fast_model": "fast-chat-prod",
        "exporter": "otlp",
        "endpoint": "http://otel-collector:4318",
        "service_name": "support-desk",
        "state": "sqlite",
        "state_path": "/var/lib/support/state.db",
        "approvals": "webhook",
        "webhook_url": "https://approvals.internal.example/hook",
        "sidecar_url": "http://harnessd:7070",
    },
    "staging on Claude": {
        "doc": "overlay",
        "env": "staging",
        "provider": "anthropic.messages",
        "fast_model": "claude-haiku-5-5",
        "effort": "low",
    },
}

TOOLS = {
    "the page's defaults": {"doc": "tool"},
    "an HTTP tool with every control": {
        "doc": "tool",
        "name": "refund_payment",
        "version": "2.1.0",
        "owner": "payments-team",
        "description": "Refund part or all of a payment.",
        "transport": "http",
        "url": "https://payments.internal.example/refunds",
        "headers_env": "Authorization=PAYMENTS_TOKEN, X-Tenant=PAYMENTS_TENANT",
        "arguments": "order_id: string\namount_usd: number\nnote?: string",
        "side_effect": "write_external",
        "risk": "high",
        "data_access": "pii:customer",
        "egress": "payments.internal.example",
        "scopes": "payments:refund",
        "tenants": "acme",
        "rate_principal": "10/m",
        "rate_tenant": "200/h",
        "approval_when": "args.amount_usd > 100",
        "approver_role": "finance",
        "max_bytes": "20000",
        "sanitize_pii": "on",
        "sanitize_instructions": "on",
        "timeout": "30s",
    },
    "sandboxed code": {
        "doc": "tool",
        "name": "run_python",
        "description": "Run a short Python snippet.",
        "transport": "code",
        "arguments": "code: string\nvalues?: object",
        "side_effect": "none",
        "risk": "medium",
        "label": "trusted",
    },
}

EVALS = {
    "the page's defaults": {"doc": "eval"},
    "graded text and guards": {
        "doc": "eval",
        "suite": "redteam",
        "grade_schema": "",
        "contains": "Hello",
        "status": "completed",
        "guard_fired": "extraction-pii",
        "pass_rate": "1",
        "case_id": "pii-in-the-request",
        "case_input": "I am ann@example.com",
        "case_expect": "Hello.",
    },
}

CHOICES = {
    "harness": APPS,
    "profile": PROFILES,
    "overlay": OVERLAYS,
    "tool": TOOLS,
    "eval": EVALS,
}


@pytest.fixture(scope="module")
def generated() -> dict[str, dict[str, dict[str, Any]]]:
    """buildSpec's result for each set of choices, by document, run once for the module."""
    flat = [(doc, name, chosen) for doc, cases in CHOICES.items() for name, chosen in cases.items()]
    results = generate(*(chosen for _, _, chosen in flat))
    out: dict[str, dict[str, dict[str, Any]]] = {doc: {} for doc in CHOICES}
    for (doc, name, _), result in zip(flat, results, strict=True):
        out[doc][name] = result
    return out


@pytest.mark.parametrize("choice", APPS)
def test_an_app_spec_loads_once_its_files_exist(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    result = generated["harness"][choice]
    assert result["file"] == "harness.yaml"
    write(tmp_path, result)
    check(tmp_path, result)


@pytest.mark.parametrize("choice", PROFILES)
def test_a_profile_loads_under_an_app_that_extends_it(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    result = generated["profile"][choice]
    profile = yaml.safe_load(result["yaml"])
    assert profile["kind"] == "Profile"
    # Wherever the page says to put it, it loads as an org profile from a profile directory.
    name, version = profile["metadata"]["name"], profile["metadata"]["version"]
    (tmp_path / "org").mkdir()
    (tmp_path / "org" / f"{name}.yaml").write_text(result["yaml"])
    extends = [f"org://{name}@^{version}", "profile://extraction"]
    write_app(tmp_path, app_under(profile, generated), extends=extends)
    check(tmp_path, {**result, "check": ["harnessweaver spec validate --profile-dir org"]})


def app_under(profile: dict[str, Any], generated: dict[str, dict[str, dict[str, Any]]]) -> Any:
    """The page's default app spec, under a profile: without its own models when the
    profile sets the gateway, which it may lock."""
    app = generated["harness"]["the page's defaults"]
    if "provider" not in profile.get("models", {}):
        return app
    spec = yaml.safe_load(app["yaml"])
    del spec["models"]
    return {**app, "yaml": json.dumps(spec)}


def test_each_kind_of_profile_says_where_it_goes_and_how_apps_extend_it(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    org = generated["profile"]["the page's defaults"]
    assert org["file"] == "profiles/acme-baseline.yaml"
    assert org["check"] == ["harnessweaver spec validate harness.yaml --profile-dir profiles"]
    assert 'extends: ["org://acme-baseline@^1"]' in org["use"]
    team = generated["profile"]["a team profile with every control"]
    assert team["file"] == ".harness/profiles/support-defaults.yaml"
    assert team["check"] == ["harnessweaver spec validate harness.yaml"]
    # Below 1.0, a caret range keeps the minor version.
    assert 'extends: ["org://support-defaults@^0.3.0"]' in team["use"]
    plugin = generated["profile"]["a plugin's profile"]
    assert plugin["file"] == "profiles/baseline.yaml"
    assert 'profiles={"baseline": "profiles/baseline.yaml"}' in plugin["use"]
    assert 'extends: ["profile://acme.baseline@^1"]' in plugin["use"]
    # It is loaded from its plugin, which its allow-list must name.
    assert yaml.safe_load(plugin["yaml"])["plugins"]["allow"] == [
        "openai",
        "anthropic",
        "otel",
        "acme",
    ]


def test_the_team_profile_loads_where_the_page_puts_it(
    generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    result = generated["profile"]["a team profile with every control"]
    write(tmp_path, result)
    app = app_under(yaml.safe_load(result["yaml"]), generated)
    write_app(tmp_path, app, extends=["org://support-defaults@^0.3.0", "profile://extraction"])
    check(tmp_path, result)


# Switching the baseline's PII guard off is changing a locked item (RULES R1).
DISABLED_PII = {"id": "acme-baseline-pii", "use": "pii.regex", "enabled": False}


@pytest.mark.parametrize(
    ("overlay", "broken"),
    [
        ({"observability": {"capture_content": True}}, "observability.capture_content"),
        (
            {
                "guardrails": {
                    "input": [{"id": "acme-baseline-pii", "use": "pii.regex", "enabled": False}]
                }
            },
            "acme-baseline-pii",
        ),
        ({"budgets": {"per_run": {"max_usd": 8}}}, "budgets.per_run.max_usd"),
    ],
)
def test_the_locks_and_bounds_of_the_default_profile_bind_its_apps(
    overlay: dict[str, Any],
    broken: str,
    generated: dict[str, dict[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    result = generated["profile"]["the page's defaults"]
    write(tmp_path, result)
    app = generated["harness"]["the page's defaults"]
    write_app(tmp_path, app, extends=["org://acme-baseline@^1", "profile://extraction"])
    (tmp_path / "harness.loose.yaml").write_text(json.dumps(overlay))
    env = {**os.environ, "HARNESSWEAVER_TEST_MODE": "1"}
    done = subprocess.run(
        [CLI, "spec", "validate", "harness.yaml", "--profile-dir", "profiles", "-e", "loose"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0
    assert broken in done.stdout + done.stderr


@pytest.mark.parametrize("choice", OVERLAYS)
def test_an_overlay_loads_over_the_app_spec(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    result = generated["overlay"][choice]
    write_app(tmp_path, generated["harness"]["the page's defaults"])
    write(tmp_path, result)
    check(tmp_path, result)


@pytest.mark.parametrize("choice", TOOLS)
def test_a_tool_manifest_loads_in_an_app_that_uses_the_tool(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    result = generated["tool"][choice]
    name = yaml.safe_load(result["yaml"])["metadata"]["name"]
    assert result["file"] == f"tools/{name}.tool.yaml"
    app = generated["harness"]["the page's defaults"]
    tasks = yaml.safe_load(app["yaml"])["tasks"]
    tasks["support"]["tools"] = [name]
    write_app(tmp_path, app, tools={"manifests": ["tools/*.tool.yaml"]}, tasks=tasks)
    write(tmp_path, result)
    # tools pin writes the digest into the manifest, and doctor then finds it pinned.
    check(tmp_path, result)
    assert "definition_digest: sha256:" in (tmp_path / result["file"]).read_text()


@pytest.mark.parametrize("choice", EVALS)
def test_an_eval_suite_passes_offline(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    # The page's own app spec and offline overlay, with the scripted model's "Hello."
    result = generated["eval"][choice]
    app = generated["harness"]["the page's defaults"]
    write_app(tmp_path, app, evals={"support": [result["file"]]})
    write(tmp_path, generated["overlay"]["the page's defaults"])
    write(tmp_path, result)
    check(tmp_path, result)


def test_the_defaults_write_this_app_spec(generated: dict[str, dict[str, dict[str, Any]]]) -> None:
    # What every reader sees first, written out by hand from the page's design.
    result = generated["harness"]["the page's defaults"]
    assert result["yaml"] == (
        "# harness.yaml, written by the HarnessWeaver spec generator.\n"
        "# Check it with: harnessweaver spec validate harness.yaml\n"
        "apiVersion: harnessweaver/v1\n"
        "kind: Harness\n"
        "metadata:\n"
        "  name: support-desk\n"
        "  owner: support-team\n"
        "  risk_tier: internal\n"
        'extends: ["profile://extraction"]\n'
        "models:\n"
        "  provider: openai.chat\n"
        "  base_url: http://localhost:4000\n"
        "  api_key_env: LITELLM_API_KEY\n"
        "  default: fast\n"
        "  aliases:\n"
        "    fast: your-fast-model\n"
        "tasks:\n"
        "  support:\n"
        "    version: 1.0.0\n"
        "    runner: direct\n"
        "    prompt: support@1\n"
        "    output: str\n"
        "    budget:\n"
        "      max_model_calls: 3\n"
        "      max_usd: 0.05\n"
        "evals:\n"
        "  support: [evals/golden.yaml]\n"
    )
    assert result["files"] == [
        {"path": "prompts/support@1.md", "kind": "prompt"},
        {"path": "evals/golden.yaml", "kind": "dataset", "name": "support"},
    ]
    assert 'await harness.run("support", ' in result["use"]


def test_the_defaults_write_this_profile(generated: dict[str, dict[str, dict[str, Any]]]) -> None:
    # An org baseline: reviewed plugins, guards in shadow mode until evals back them (R8),
    # capped budgets, a required level by risk tier, and locks and bounds that hold them.
    assert generated["profile"]["the page's defaults"]["yaml"] == (
        "# profiles/acme-baseline.yaml, written by the HarnessWeaver spec generator.\n"
        "# Check it with: harnessweaver spec validate harness.yaml --profile-dir profiles\n"
        "apiVersion: harnessweaver/v1\n"
        "kind: Profile\n"
        "metadata:\n"
        "  name: acme-baseline\n"
        "  version: 1.0.0\n"
        "  owner: platform-security\n"
        "plugins:\n"
        "  allow: [openai, anthropic, otel]\n"
        "models:\n"
        "  allowed_aliases: [fast, strong]\n"
        "guardrails:\n"
        "  input:\n"
        "    - id: acme-baseline-pii\n"
        "      use: pii.regex\n"
        "      action: redact\n"
        "      mode: log_only\n"
        "  output:\n"
        "    - id: acme-baseline-secrets\n"
        "      use: secrets.scan\n"
        "      action: block\n"
        "      mode: log_only\n"
        "tools:\n"
        "  require_manifest: true\n"
        "  approval_by_risk:\n"
        "    high: required\n"
        "    critical: required\n"
        "budgets:\n"
        "  per_run:\n"
        "    max_usd: 2\n"
        "    deadline: 5m\n"
        "observability:\n"
        "  capture_content: false\n"
        "require_level:\n"
        "  default: L1\n"
        "  tiers:\n"
        "    customer_facing: L2\n"
        "    takes_actions: L3\n"
        "locks:\n"
        "  - plugins.allow\n"
        '  - "guardrails.input[acme-baseline-pii]"\n'
        '  - "guardrails.output[acme-baseline-secrets]"\n'
        "  - tools.require_manifest\n"
        "  - tools.approval_by_risk\n"
        "  - observability.capture_content\n"
        "bounds:\n"
        "  budgets.per_run.max_usd:\n"
        "    max: 5\n"
        "  budgets.per_run.deadline:\n"
        "    max: 30m\n"
        '  "tasks.*.budget.max_usd":\n'
        "    max: 2\n"
    )


def test_the_defaults_write_this_overlay(generated: dict[str, dict[str, dict[str, Any]]]) -> None:
    result = generated["overlay"]["the page's defaults"]
    assert result["file"] == "harness.offline.yaml"
    assert result["yaml"] == (
        "# harness.offline.yaml, written by the HarnessWeaver spec generator.\n"
        "# Check it with: harnessweaver spec validate harness.yaml -e offline\n"
        "apiVersion: harnessweaver/v1\n"
        "kind: Overlay\n"
        "models:\n"
        "  provider: scripted\n"
        "  replies:\n"
        "    - text: Hello.\n"
    )
    assert "HARNESSWEAVER_ENV=offline" in result["use"]


def test_the_defaults_write_this_tool_manifest(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    result = generated["tool"]["the page's defaults"]
    assert result["yaml"] == (
        "# tools/lookup_order.tool.yaml, written by the HarnessWeaver spec generator.\n"
        "# Check it with: harnessweaver tools pin harness.yaml && harnessweaver doctor"
        " harness.yaml\n"
        "apiVersion: harnessweaver/v1\n"
        "kind: Tool\n"
        "metadata:\n"
        "  name: lookup_order\n"
        "  version: 1.0.0\n"
        "spec:\n"
        "  transport: native\n"
        "  handler: app.tools:lookup_order\n"
        '  description: "Look up an order by its id."\n'
        "  input_schema:\n"
        "    type: object\n"
        "    properties:\n"
        "      order_id:\n"
        "        type: string\n"
        "    required: [order_id]\n"
        "  side_effect: read\n"
        "  risk: low\n"
    )
    assert result["files"] == [{"path": "app/tools.py", "kind": "function", "name": "lookup_order"}]


def test_the_defaults_write_this_eval_suite(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    result = generated["eval"]["the page's defaults"]
    assert result["file"] == "evals/golden.yaml"
    assert result["yaml"] == (
        "# evals/golden.yaml, written by the HarnessWeaver spec generator.\n"
        "# Check it with: harnessweaver eval run harness.yaml -e offline\n"
        "suite: golden\n"
        "task: support\n"
        "graders: [schema_valid]\n"
        "cases:\n"
        "  - id: first\n"
        '    input: "Where is my order?"\n'
    )


def test_an_app_with_no_task_has_a_run_budget_and_no_model_when_it_wraps_one(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    wrapped = yaml.safe_load(generated["harness"]["a wrapped OpenAI client"]["yaml"])
    assert "tasks" not in wrapped
    assert "models" not in wrapped
    assert "evals" not in wrapped
    assert wrapped["budgets"] == {"per_run": {"max_model_calls": 3, "max_usd": 0.02}}
    assert "harness.instrument(" in generated["harness"]["a wrapped OpenAI client"]["use"]
    session = yaml.safe_load(generated["harness"]["a session with no task"]["yaml"])
    assert "tasks" not in session
    assert session["models"]["provider"] == "anthropic.messages"
    assert session["routing"] == {
        "topic": {
            "options": ["orders", "billing", "other"],
            "cascade": [
                {
                    "id": "examples",
                    "use": "lexical",
                    "utterances": {"orders": ["where is my order"], "billing": ["refund"]},
                }
            ],
            "default": "other",
        }
    }
    assert session["memory"] == {"use": "memory"}


# Loads harness.yaml with the TypeScript core (argv[1]), as a TypeScript app does, and
# opens a session, on the task in argv[2] if there is one: the input guard, the router, the
# knowledge base and, in a task, a governed tool call. Prints what each returned.
TS_RUN = """
import { pathToFileURL } from "node:url";
const { load } = await import(pathToFileURL(process.argv[1]).href);
const task = process.argv[2] || null;
const lookup_order = async ({ order_id }) => ({ order_id, status: "shipped" });
const harness = load("harness.yaml", { tools: { lookup_order } });
const answers = await harness.session({ task, principal: "ann" }, async (s) => ({
  guarded: await s.guard("input", "I am ann@example.com"),
  route: (await s.decide("intent", { text: "please refund my order" })).choice,
  documents: (await s.context("kb").fetch("refund")).map((item) => item.id),
  tool: task ? await s.tool("lookup_order", { order_id: "A-1001" }) : null,
}));
process.stdout.write(JSON.stringify(answers));
"""


@pytest.mark.parametrize("choice", ["TypeScript", "TypeScript, with no task"])
def test_a_typescript_app_spec_loads_and_runs_in_the_typescript_core(
    choice: str, generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    # make check runs without the TypeScript build, which the TypeScript CI job makes and
    # then requires (REQUIRE_TS_CORE).
    if not TS_CORE.exists():
        if os.environ.get("REQUIRE_TS_CORE"):
            pytest.fail(f"no TypeScript core at {TS_CORE}; run pnpm -C typescript build")
        pytest.skip("needs the TypeScript core: pnpm -C typescript build")
    result = generated["harness"][choice]
    write(tmp_path, result)
    (tmp_path / "data" / "kb.yaml").write_text(
        "documents:\n  - { id: kb-refunds, content: A refund takes five days. }\n"
    )
    task = next(iter(yaml.safe_load(result["yaml"]).get("tasks", {})), "")
    done = subprocess.run(
        ["node", "--input-type=module", "-e", TS_RUN, str(TS_CORE), task],
        cwd=tmp_path,
        env={**os.environ, "HARNESSWEAVER_TEST_MODE": "1"},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (result["yaml"], done.stderr)
    assert json.loads(done.stdout) == {
        "guarded": "I am [EMAIL]",
        "route": "billing",
        "documents": ["kb-refunds"],
        "tool": {"order_id": "A-1001", "status": "shipped"} if task else None,
    }


def test_a_plugins_profile_loads_from_the_installed_plugin(
    generated: dict[str, dict[str, dict[str, Any]]], tmp_path: Path
) -> None:
    # The plugin package the page describes, installed as pip would: its module, the
    # profile inside it, and the dist-info whose entry point names the plugin.
    result = generated["profile"]["a plugin's profile"]
    named = re.search(r"profiles=(\{.*?\})", result["use"])
    pinned = re.search(r"extends: (\[.*\])", result["use"])
    assert named, result["use"]
    assert pinned, result["use"]
    profiles = json.loads(named[1])
    extends = json.loads(pinned[1])
    site = tmp_path / "site"
    package = site / "acme_harness"
    for path in profiles.values():
        (package / path).parent.mkdir(parents=True, exist_ok=True)
        (package / path).write_text(result["yaml"])
    (package / "__init__.py").write_text(
        f"import harnessweaver as hw\n\nplugin = hw.Plugin(namespace='acme', version='0.1.0', "
        f"profiles={profiles!r})\n"
    )
    info = site / "acme_harness-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: acme-harness\nVersion: 0.1.0\n")
    (info / "entry_points.txt").write_text("[harnessweaver.plugins]\nacme = acme_harness:plugin\n")
    app = app_under(yaml.safe_load(result["yaml"]), generated)
    write_app(tmp_path, app, extends=[*extends, "profile://extraction"])
    env = {**os.environ, "HARNESSWEAVER_TEST_MODE": "1", "PYTHONPATH": str(site)}
    done = subprocess.run(
        [CLI, "spec", "explain", "harness.yaml"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (result["yaml"], done.stdout, done.stderr)
    # The profile's own guard reached the app, from the plugin's layer.
    assert "baseline-pii" in done.stdout


def test_a_typescript_app_leaves_runners_approvals_state_and_telemetry_to_python(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    # TypeScript runs sessions and governs the models it is given (wrapModel). The model
    # provider stays, for Python, which runs the task in harnessd and loads the spec in
    # spec validate; the runner, approvals, state, telemetry and evals are Python's.
    result = generated["harness"]["TypeScript"]
    spec = yaml.safe_load(result["yaml"])
    assert spec["models"]["provider"] == "openai.chat"
    assert spec["models"]["prices"] == {
        "your-fast-model": {"input_per_mtok": 0.15, "output_per_mtok": 0.6}
    }
    assert spec["tasks"]["support"].keys() == {"version", "output", "tools", "budget"}
    assert "evals" not in spec
    assert spec["tasks"]["support"]["tools"] == ["lookup_order"]
    assert "observability" not in spec
    assert "routing" in spec
    assert "context" in spec
    assert 'load("harness.yaml"' in result["use"]


def test_plugin_middleware_and_sidecar_guards(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    spec = yaml.safe_load(generated["harness"]["plugins and guards in harnessd"]["yaml"])
    assert spec["plugins"] == {"local": ["app.harness_plugin"]}
    assert spec["middleware"] == [
        {"id": "no_weekend_refunds", "use": "acme.no_weekend_refunds"},
        {"id": "audit", "use": "acme.audit"},
    ]
    assert {guard["where"] for guard in spec["guardrails"]["input"]} == {"sidecar"}
    assert spec["sidecar"] == {"url": "http://127.0.0.1:7070"}


def test_the_install_commands_name_what_each_document_uses(
    generated: dict[str, dict[str, dict[str, Any]]],
) -> None:
    apps = generated["harness"]
    assert apps["the page's defaults"]["install"] == [
        'uv add "harnessweaver[openai]"',
        "uv add --dev harnessweaver-cli",
    ]
    assert apps["typed tools with every control"]["install"][0] == (
        'uv add "harnessweaver[anthropic,otel]"'
    )
    assert apps["your own steps, offline"]["install"][0] == 'uv add "harnessweaver[otel]"'
    assert apps["a Pydantic AI agent"]["install"][0] == 'uv add "harnessweaver[openai,pydantic-ai]"'
    assert apps["a wrapped OpenAI client"]["install"][0] == 'uv add "harnessweaver[openai]"'
    assert apps["a wrapped Pydantic AI agent"]["install"][0] == (
        'uv add "harnessweaver[pydantic-ai]"'
    )
    assert apps["TypeScript"]["install"] == [
        "npm install @harnessweaver/core @harnessweaver/ai-sdk ai @ai-sdk/provider",
        'uv tool install harnessweaver-cli --with "harnessweaver[openai]"',
    ]
    assert apps["plugins and guards in harnessd"]["install"] == [
        'uv add "harnessweaver[openai]"',
        "uv add --dev harnessweaver-cli",
        "uv tool install harnessweaver-sidecar",
    ]
    assert generated["overlay"]["the page's defaults"]["install"] == []
    assert generated["overlay"]["production"]["install"] == ['uv add "harnessweaver[openai,otel]"']
    assert generated["tool"]["the page's defaults"]["install"] == []
    assert generated["tool"]["sandboxed code"]["install"] == ['uv add "harnessweaver[monty]"']
    assert generated["profile"]["the page's defaults"]["install"] == []


def test_middleware_from_an_installed_plugin_says_to_install_it() -> None:
    (result,) = generate({"middleware": "acme.no_weekend_refunds"})
    assert "plugins" not in yaml.safe_load(result["yaml"])
    assert result["install"][-1] == "uv add <the package of the plugin acme>"


def test_an_eval_case_reads_json_as_a_value_and_anything_else_as_text() -> None:
    results = generate(
        {"doc": "eval", "case_input": '{"text": "Hi"}', "case_expect": '{"category": "billing"}'},
        {"doc": "eval", "case_input": "Hi", "case_expect": "42"},
        {"doc": "eval", "field_equals": "category, total", "rubric": "Polite and correct."},
    )
    cases = [yaml.safe_load(result["yaml"])["cases"][0] for result in results]
    assert cases[0]["input"] == {"text": "Hi"}
    assert cases[0]["expect"] == {"category": "billing"}
    assert cases[1]["input"] == "Hi"
    assert cases[1]["expect"] == 42
    assert yaml.safe_load(results[2]["yaml"])["graders"] == [
        "schema_valid",
        {"field_equals": "category"},
        {"field_equals": "total"},
        {"llm_judge": "Polite and correct."},
    ]


def test_every_form_names_its_document() -> None:
    # Each form submits the document it writes, which picks buildSpec's writer.
    forms = page_defaults()
    assert sorted(forms) == sorted(CHOICES)
    assert all(values["doc"] == doc for doc, values in forms.items())


# Text YAML would read as something else, or not at all, unless it is quoted.
AWKWARD = [
    "yes",
    "No",
    "null",
    "~",
    "1.5",
    "0x1F",
    "1e3",
    "a: b",
    "#team",
    "x:",
    "- x",
    "@x",
    "[x]",
    "{x}",
    "it's",
    'say "hi"',
    "caf\u00e9",
    " padded",
    "two\nlines",
    "back\\slash",
]


def test_awkward_text_reads_back_as_written() -> None:
    results = generate(
        *({"owner": text, "rule_reason": text, "rule_when": "true"} for text in AWKWARD),
        *({"doc": "tool", "description": text} for text in AWKWARD),
    )
    for text, result in zip(AWKWARD, results[: len(AWKWARD)], strict=True):
        spec = yaml.safe_load(result["yaml"])
        assert spec["metadata"]["owner"] == text.strip()
        assert spec["policy"]["rules"][0]["reason"] == text.strip()
    for text, result in zip(AWKWARD, results[len(AWKWARD) :], strict=True):
        tool = yaml.safe_load(result["yaml"])["spec"]
        assert tool["description"] == text.strip()


def test_a_long_list_is_written_one_item_a_line() -> None:
    (result,) = generate({"doc": "profile", "locks": "a.b, c.d, e.f, g.h, i.j, k.l"})
    assert "locks:\n  - plugins.allow\n" in result["yaml"]
    assert yaml.safe_load(result["yaml"])["locks"][-1] == "k.l"
