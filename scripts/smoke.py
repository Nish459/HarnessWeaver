"""Smoke-test the packages as users get them: installed from PyPI and npm, then tried offline.

Each package gets an environment of its own, made fresh: a virtual environment on Python 3.12
for a PyPI package, and an empty npm project for an npm package. The package is installed from
its registry, never from this checkout, with the newest dependencies the registry offers, and
then put through the quick offline check in ``CHECKS``: the conformance suite for the core and
each plugin (RULES T5), a project made from a template and checked with the CLI, a running
harnessd, and a guarded session in TypeScript.

A package is installed at the version its release tag on HEAD names (``<package>@<version>``,
as for scripts/release.py), or at the latest version on its registry when HEAD has no tag for
it. So after a release the new versions are tried, and so are the packages that weren't
released, with the new versions they now get. A registry can take a few minutes to serve a
version it has just been sent, so an install is retried for a while before it counts as failed.

Usage::

    python scripts/smoke.py [PACKAGE ...]     # every package, or just the named ones

The Release workflow runs it once the packages are published (CONTRIBUTING.md, Releasing).
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

from release import Package, git, packages

# The oldest Python and Node the packages support (requires-python, engines): where a fresh
# install is the likeliest to break. The Release workflow sets up Node 22.
PYTHON = "3.12"
ATTEMPTS = 10
DELAY = 30  # seconds between install attempts, so a release waits up to about five minutes

# The core: one task on a scripted model through the extraction profile, whose input guard
# must find the e-mail address, so the loader, the hook bus, the guards and a runner all run.
# The spec is JSON, which every YAML 1.2 reader reads.
CORE_RUN = """
import asyncio, json, pathlib
import harnessweaver as hw

spec = {
    "apiVersion": "harnessweaver/v1", "kind": "Harness", "metadata": {"name": "smoke"},
    "extends": ["profile://extraction"],
    "models": {"provider": "scripted", "replies": [{"text": "Hello."}]},
    "tasks": {"greet": {"output": "str"}},
}
pathlib.Path("harness.yaml").write_text(json.dumps(spec))
harness = hw.load("harness.yaml")
result = asyncio.run(harness.run("greet", "I am ann@example.com", principal="smoke"))
assert result.status == "completed" and result.output == "Hello.", result
assert any(event.code == "guard_fired" for event in result.trace), "the PII guard didn't fire"
"""

# The sidecar: harnessd serves a spec on a free local port, answers its health check, and
# serves the spec to a caller with the bearer token (RULES S6).
SIDECAR_RUN = """
import json, os, pathlib, socket, subprocess, time, urllib.request

spec = {"apiVersion": "harnessweaver/v1", "kind": "Harness", "metadata": {"name": "smoke"}}
pathlib.Path("harness.yaml").write_text(json.dumps(spec))
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
url = f"http://127.0.0.1:{port}/v1"
env = {**os.environ, "HARNESSD_TOKEN": "smoke-token"}
server = subprocess.Popen(["harnessd", "harness.yaml", "--port", str(port)], env=env)
try:
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "/health") as response:
                assert json.load(response)["status"] == "ok"
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit("harnessd didn't answer its health check")
    asked = urllib.request.Request(url + "/spec", headers={"Authorization": "Bearer smoke-token"})
    with urllib.request.urlopen(asked) as response:
        assert json.load(response)["name"] == "smoke"
finally:
    server.terminate()
    server.wait()
"""

# The TypeScript core: the extraction profile's input guard redacts the e-mail address.
TS_CORE_RUN = """
import { writeFileSync } from "node:fs";
import { load } from "@harnessweaver/core";

const spec = { apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "smoke" } };
writeFileSync("harness.yaml", JSON.stringify({ ...spec, extends: ["profile://extraction"] }));
const harness = load("harness.yaml");
const text = await harness.session(
  { principal: "smoke" },
  (s) => s.guard("input", "I am ann@example.com"),
);
if (text !== "I am [EMAIL]") throw new Error(`the PII guard returned ${JSON.stringify(text)}`);
"""

# The AI SDK middleware: a mock AI SDK model answers through wrapModel inside a session.
TS_AI_SDK_RUN = """
import { writeFileSync } from "node:fs";
import { load } from "@harnessweaver/core";
import { wrapModel } from "@harnessweaver/ai-sdk";
import { generateText } from "ai";
import { MockLanguageModelV4 } from "ai/test";

const spec = { apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "smoke" } };
writeFileSync("harness.yaml", JSON.stringify(spec));
const usage = {
  inputTokens: { total: 4, noCache: 4, cacheRead: 0, cacheWrite: 0 },
  outputTokens: { total: 2, text: 2, reasoning: 0 },
};
const model = new MockLanguageModelV4({
  doGenerate: {
    content: [{ type: "text", text: "Hello." }],
    finishReason: { unified: "stop", raw: "stop" },
    usage,
    warnings: [],
  },
});
const text = await load("harness.yaml").session({ principal: "smoke" }, async (s) => {
  const result = await generateText({ model: wrapModel(s, model), prompt: "Hi" });
  return result.text;
});
if (text !== "Hello.") throw new Error(`the wrapped model returned ${JSON.stringify(text)}`);
"""


class Check(NamedTuple):
    """How to try one package once it is installed.

    Attributes:
        commands: Run one after another in an empty folder, with the package's environment
            first on PATH. Each must exit with 0.
        install: Installed with the package: what the commands need, such as pytest.
    """

    commands: list[list[str]]
    install: list[str]


def conformance(namespace: str) -> Check:
    """The conformance suite (RULES T5) on one plugin, run by the core it was installed with."""
    command = ["python", "-m", "pytest", "-q", f"--harnessweaver-conformance={namespace}"]
    return Check([command], ["pytest"])


CHECKS: dict[str, Check] = {
    "harnessweaver": Check(
        [["python", "-c", CORE_RUN], *conformance("harnessweaver").commands], ["pytest"]
    ),
    # A template's project is checked and its golden evals pass offline, which also proves
    # that the templates are in the wheel.
    "harnessweaver-cli": Check(
        [
            ["harnessweaver", "init", "demo"],
            ["harnessweaver", "spec", "validate", "demo/harness.yaml", "-e", "offline"],
            ["harnessweaver", "eval", "run", "demo/harness.yaml", "-e", "offline"],
        ],
        [],
    ),
    "harnessweaver-sidecar": Check([["python", "-c", SIDECAR_RUN]], []),
    "harnessweaver-openai": conformance("openai"),
    "harnessweaver-anthropic": conformance("anthropic"),
    "harnessweaver-pydantic-ai": conformance("pydantic_ai"),
    "harnessweaver-monty": conformance("monty"),
    "harnessweaver-otel": conformance("otel"),
    "harnessweaver-cel": conformance("cel"),
    "@harnessweaver/core": Check([["node", "--input-type=module", "-e", TS_CORE_RUN]], []),
    # npm installs the peer dependencies, ai and @ai-sdk/provider, by itself.
    "@harnessweaver/ai-sdk": Check([["node", "--input-type=module", "-e", TS_AI_SDK_RUN]], []),
}


def install(command: list[str | Path], cwd: Path) -> bool:
    """Run an install command until it succeeds, waiting between attempts for a registry to
    serve a version it has just been sent.

    Returns:
        Whether an attempt succeeded.
    """
    for attempt in range(1, ATTEMPTS + 1):
        if subprocess.run(command, cwd=cwd, check=False).returncode == 0:
            return True
        if attempt < ATTEMPTS:
            print(
                f"install failed ({attempt} of {ATTEMPTS} attempts); again in {DELAY}s", flush=True
            )
            time.sleep(DELAY)
    return False


def run_checks(name: str, bin_dir: Path, cwd: Path) -> bool:
    """Run a package's check in ``cwd``, with the commands in ``bin_dir`` first on PATH.

    Returns:
        Whether every command passed; the first failure stops the rest.
    """
    path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    # Test mode makes every live provider refuse the network (RULES R14).
    env = {**os.environ, "PATH": path, "HARNESSWEAVER_TEST_MODE": "1"}
    return all(
        subprocess.run(command, cwd=cwd, env=env, check=False).returncode == 0
        for command in CHECKS[name].commands
    )


def smoke(package: Package, version: str | None) -> bool:
    """Install one package into a fresh environment from its registry, then run its check.

    Args:
        package: The package.
        version: The version to install, or None for the registry's latest.

    Returns:
        Whether it installed and passed its check.

    Raises:
        subprocess.CalledProcessError: If uv can't make the virtual environment.
    """
    check = CHECKS[package.name]
    with tempfile.TemporaryDirectory(prefix="harnessweaver-smoke-") as temporary:
        # Outside the checkout, so neither uv nor npm finds the workspace or its settings.
        work = Path(temporary) / "work"
        work.mkdir()
        if package.manifest.name == "pyproject.toml":
            env = Path(temporary) / "env"
            subprocess.run(
                ["uv", "venv", "--quiet", "--no-cache", "--python", PYTHON, env],
                cwd=work,
                check=True,
            )
            wanted = f"{package.name}=={version}" if version else package.name
            # No cache, so each attempt asks the registry again, past an index page it cached.
            command: list[str | Path] = ["uv", "pip", "install", "--no-cache"]
            command += ["--python", env / "bin" / "python", wanted, *check.install]
            bin_dir = env / "bin"
        else:
            (work / "package.json").write_text('{"private": true}\n')
            wanted = f"{package.name}@{version}" if version else package.name
            command = ["npm", "install", "--prefer-online", "--no-audit", "--no-fund"]
            command += [wanted, *check.install]
            bin_dir = work / "node_modules" / ".bin"
        return install(command, work) and run_checks(package.name, bin_dir, work)


def main(argv: list[str]) -> int:
    """Smoke-test every package, or the named ones, and print what passed.

    Args:
        argv: The names of the packages to try; none tries them all.

    Returns:
        0 when every package passed, 1 when one failed, 2 for a name that isn't a package.
    """
    known = packages()
    unknown = [name for name in argv if name not in known]
    if unknown:
        print(f"Not a package here: {', '.join(unknown)}", file=sys.stderr)
        print(f"The packages: {', '.join(known)}", file=sys.stderr)
        return 2
    # A release tag is <package>@<version>, and the last "@" splits the version off.
    tagged = {}
    for tag in git("tag", "--points-at", "HEAD").split():
        name, _, version = tag.rpartition("@")
        tagged[name] = version
    passed: dict[str, bool] = {}
    for name in argv or known:
        print(f"--- {name} {tagged.get(name, 'latest')}", flush=True)
        passed[name] = smoke(known[name], tagged.get(name))
    print("Smoke tests:")
    for name, ok in passed.items():
        print(f"  {'passed' if ok else 'FAILED'}  {name} {tagged.get(name, 'latest')}")
    return 0 if all(passed.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
