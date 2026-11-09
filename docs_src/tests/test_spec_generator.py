"""The spec generator page writes specs that load (docs/javascripts/spec-generator.js).

The page's ``buildSpec`` runs under Node.js on sets of form choices, starting from the
page's own defaults. For each spec it writes, the test creates a stub of every file the page
tells the reader to create, then runs ``harnessweaver spec validate`` on it, which must pass:
that is what the page promises a reader who creates those files.
"""

import json
import os
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
PAGE = ROOT / "docs" / "learn" / "spec-generator.md"
CLI = Path(sys.executable).parent / "harnessweaver"

# Reads the JSON list of form values on stdin and prints buildSpec's result for each.
RUN = """
const { buildSpec } = require(process.argv[1]);
const cases = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(buildSpec)));
"""


class FormDefaults(HTMLParser):
    """The values the page's form submits before the reader changes anything, as the
    browser's ``FormData`` reports them: a checked box is ``on``, a select its selected
    option, or else its first."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self._select: str | None = None
        self._picked = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record an input's value, or an option's when it is its select's first or selected."""
        a = {key: value or "" for key, value in attrs}
        if tag == "input" and "name" in a:
            if a.get("type") != "checkbox":
                self.values[a["name"]] = a.get("value", "")
            elif "checked" in a:
                self.values[a["name"]] = "on"
        elif tag == "select":
            self._select, self._picked = a["name"], False
        elif tag == "option" and self._select is not None and not self._picked:
            if self._select not in self.values or "selected" in a:
                self.values[self._select] = a.get("value", "")
            self._picked = "selected" in a

    def handle_endtag(self, tag: str) -> None:
        """Leave a select."""
        if tag == "select":
            self._select = None


def page_defaults() -> dict[str, str]:
    """The page form's default values."""
    parser = FormDefaults()
    parser.feed(PAGE.read_text())
    return parser.values


def generate(*choices: dict[str, str]) -> list[dict[str, Any]]:
    """Run buildSpec on each set of choices, laid over the page's defaults.

    Returns:
        Each result: the ``yaml``, the ``files`` it refers to, and the ``install`` commands.
    """
    node = shutil.which("node")
    assert node, "the spec generator's tests run it with Node.js 22 or later (AGENTS.md)"
    cases = [page_defaults() | chosen for chosen in choices]
    done = subprocess.run(
        [node, "-e", RUN, str(GENERATOR)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


# Stubs for each kind of file a spec refers to: enough for the spec to load.
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
}


def create_files(folder: Path, files: list[dict[str, str]]) -> None:
    """Write a stub of every file the page lists, appending what shares a file."""
    for item in files:
        if item["kind"] == "manifest":
            # The manifest names the tool's handler, which the stub puts in app/tools.py.
            (folder / "tools").mkdir(exist_ok=True)
            (folder / item["path"]).write_text(MANIFEST.format(name=item["name"]))
            item = {"path": "app/tools.py", "kind": "function", "name": item["name"]}
        path = folder / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stub:
            stub.write(STUBS[item["kind"]].format(name=item.get("name", "")))


CHOICES = {
    "the page's defaults": {},
    "typed tools with every control": {
        "profile": "rag",
        "provider": "anthropic.messages",
        "fast_model": "claude-haiku-5-5",
        "strong_model": "claude-opus-5-5",
        "effort": "high",
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
    },
    "your own steps, offline": {
        "profile": "none",
        "provider": "scripted",
        "runner": "session",
        "kb_file": "data/kb.yaml",
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
}


@pytest.fixture(scope="module")
def generated() -> dict[str, dict[str, Any]]:
    """buildSpec's result for each set of choices, run once for the module."""
    return dict(zip(CHOICES, generate(*CHOICES.values()), strict=True))


@pytest.mark.parametrize("choice", CHOICES)
def test_a_spec_loads_once_its_files_exist(
    choice: str, generated: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    result = generated[choice]
    (tmp_path / "harness.yaml").write_text(result["yaml"])
    create_files(tmp_path, result["files"])
    env = {**os.environ, "HARNESSWEAVER_TEST_MODE": "1"}
    done = subprocess.run(
        [CLI, "spec", "validate", "harness.yaml"], cwd=tmp_path, env=env, capture_output=True
    )
    assert done.returncode == 0, (result["yaml"], done.stderr.decode())


def test_the_defaults_write_this_spec(generated: dict[str, dict[str, Any]]) -> None:
    # What every reader sees first, written out by hand from the page's design.
    assert generated["the page's defaults"]["yaml"] == (
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
    assert generated["the page's defaults"]["files"] == [
        {"path": "prompts/support@1.md", "kind": "prompt"},
        {"path": "evals/golden.yaml", "kind": "dataset"},
    ]


def test_the_install_commands_name_the_plugins_the_spec_uses(
    generated: dict[str, dict[str, Any]],
) -> None:
    assert generated["the page's defaults"]["install"] == [
        'uv add "harnessweaver[openai]"',
        "uv add --dev harnessweaver-cli",
    ]
    assert generated["typed tools with every control"]["install"][0] == (
        'uv add "harnessweaver[anthropic,otel]"'
    )
    assert generated["your own steps, offline"]["install"][0] == 'uv add "harnessweaver[otel]"'
    assert generated["a Pydantic AI agent"]["install"][0] == (
        'uv add "harnessweaver[openai,pydantic-ai]"'
    )


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
        *({"owner": text, "rule_reason": text, "rule_when": "true"} for text in AWKWARD)
    )
    for text, result in zip(AWKWARD, results, strict=True):
        spec = yaml.safe_load(result["yaml"])
        assert spec["metadata"]["owner"] == text.strip()
        assert spec["policy"]["rules"][0]["reason"] == text.strip()
