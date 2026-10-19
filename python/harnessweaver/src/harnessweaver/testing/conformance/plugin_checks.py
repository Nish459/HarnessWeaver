"""Checks on the plugin itself: metadata, names, and an inert import (S8)."""

import subprocess
import sys
import tempfile
import textwrap
from importlib.metadata import entry_points
from typing import Final

from harnessweaver.core.plugins import (
    CONTRACT_VERSION,
    ENTRY_POINT_GROUP,
    Plugin,
    check_owned,
)
from harnessweaver.core.registry import LoadedPlugin, PluginCatalog, PluginSource, import_target
from harnessweaver.spec.yaml import load_yaml
from harnessweaver.testing.conformance.common import expect

__all__ = ["check_import_is_inert", "check_plugin", "load_plugin"]


def load_plugin(selector: str, catalog: PluginCatalog | None = None) -> LoadedPlugin:
    """The plugin to check: an installed namespace, ``harnessweaver`` for the built-in
    plugin, or ``module:attribute`` for an in-repo plugin."""
    if ":" in selector:
        value = import_target(selector)
        if not isinstance(value, Plugin):
            raise AssertionError(f"{selector} is not a harnessweaver.Plugin")
        return LoadedPlugin(value, PluginSource(value.namespace, selector, "local"))
    return (catalog or PluginCatalog.discover()).load(selector)


def check_plugin(loaded: LoadedPlugin) -> None:
    """Metadata, names, contract range, profiles and templates."""
    plugin = loaded.plugin
    expect(
        plugin.contract_range.contains(CONTRACT_VERSION),
        f"contract range {plugin.contract} doesn't include {CONTRACT_VERSION} (V5)",
    )
    if loaded.source.origin == "entry_point":
        points = [ep for ep in entry_points(group=ENTRY_POINT_GROUP) if ep.name == plugin.namespace]
        expect(points, f"no {ENTRY_POINT_GROUP} entry point named {plugin.namespace!r}")
    seen: set[tuple[str, str]] = set()
    for item in plugin.contributions():
        problem = check_owned(plugin, item)
        if problem is not None:
            raise AssertionError(problem)
        expect(item.key not in seen, f"{item.name} is contributed twice")
        seen.add(item.key)
        if item.contract is not None:
            expect(
                item.contract.contains(CONTRACT_VERSION), f"{item.name}: contract {item.contract}"
            )
    for name, path in plugin.profiles.items():
        resource = loaded.resource(path)
        expect(resource.is_file(), f"profile {name}: {path} doesn't exist")
        document = load_yaml(resource.read_text(encoding="utf-8"), f"profile {name}")
        expect(isinstance(document, dict), f"profile {name} isn't a map")
        expect(document.get("kind") == "Profile", f"profile {name} isn't a kind: Profile document")
    for name, path in plugin.templates.items():
        expect(
            loaded.resource(path).is_dir() or loaded.resource(path).is_file(),
            f"template {name}: {path} doesn't exist",
        )


_INERT_SCRIPT: Final = textwrap.dedent(
    """
    import importlib, os, socket, sys
    def refuse(*args, **kwargs):
        raise RuntimeError("network access at import time")
    socket.socket.connect = refuse
    socket.create_connection = refuse
    before = sorted(os.listdir("."))
    importlib.import_module(sys.argv[1])
    after = sorted(os.listdir("."))
    from opentelemetry import metrics, trace
    problems = []
    if before != after:
        problems.append("files created in the working directory")
    if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        problems.append("a global tracer provider was installed")
    if type(metrics.get_meter_provider()).__name__ != "_ProxyMeterProvider":
        problems.append("a global meter provider was installed")
    print("|".join(problems) or "ok")
    """
)


def check_import_is_inert(module: str) -> None:
    """Importing a plugin opens no sockets, writes no files and installs nothing global (S8)."""
    with tempfile.TemporaryDirectory() as directory:
        done = subprocess.run(
            [sys.executable, "-c", _INERT_SCRIPT, module],
            capture_output=True,
            text=True,
            cwd=directory,
            check=False,
            timeout=60,
        )
    expect(done.returncode == 0, f"importing {module} failed: {done.stderr.strip()[-500:]}")
    expect(done.stdout.strip() == "ok", f"importing {module}: {done.stdout.strip()}")
    expect(not done.stdout.strip().count("\n"), f"importing {module} printed output")
