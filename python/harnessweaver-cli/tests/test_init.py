"""``harnessweaver init`` and ``harnessweaver test``, including T6: a template's own tests pass."""

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver_cli.main import app
from harnessweaver_cli.scaffold import BUILTIN_TEMPLATES

runner = CliRunner()

TEMPLATE_FILES = {
    "README.md",
    "app/main.py",
    "app/models.py",
    "evals/golden.yaml",
    "harness.offline.yaml",
    "harness.yaml",
    "prompts/extract@1.md",
    "pyproject.toml",
    "tests/test_extract.py",
}


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_init_renders_the_extraction_template(tmp_path: Path) -> None:
    target = tmp_path / "ticket_triage"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert files(target) >= TEMPLATE_FILES
    assert "name: ticket-triage" in (target / "harness.yaml").read_text(encoding="utf-8")
    assert 'name = "ticket-triage"' in (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "__app_name__" not in "".join(
        (target / f).read_text(encoding="utf-8") for f in files(target)
    )
    assert "harnessweaver spec validate --env offline" in result.output


def test_init_never_overwrites_without_force(tmp_path: Path) -> None:
    assert runner.invoke(app, ["init", str(tmp_path), "--name", "demo"]).exit_code == 0
    (tmp_path / "harness.yaml").write_text("mine", encoding="utf-8")
    refused = runner.invoke(app, ["init", str(tmp_path), "--name", "demo"])
    assert refused.exit_code == 1
    assert "harness.yaml" in refused.output
    assert "--force" in refused.output
    assert (tmp_path / "harness.yaml").read_text(encoding="utf-8") == "mine"
    forced = runner.invoke(app, ["init", str(tmp_path), "--name", "demo", "--force"])
    assert forced.exit_code == 0
    assert (tmp_path / "harness.yaml").read_text(encoding="utf-8") != "mine"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--name", "Bad_Name"], "invalid project name"),
        (["--template", "nope"], "no template 'nope'"),
        (["--template", "nosuch.rag"], "nosuch"),
    ],
)
def test_init_refuses_bad_names_and_templates(
    tmp_path: Path, args: list[str], message: str
) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "x"), *args])
    assert result.exit_code == 1
    assert message in result.output


def test_init_renders_a_plugin_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "src" / "tplkit_plugin"
    (package / "templates" / "mini").mkdir(parents=True)
    (package / "__init__.py").write_text(
        "import harnessweaver as hw\n"
        'plugin = hw.Plugin(namespace="tplkit", version="1.0.0",\n'
        '                   templates={"mini": "templates/mini"})\n',
        encoding="utf-8",
    )
    (package / "templates" / "mini" / "harness.yaml").write_text(
        "metadata: { name: __app_name__ }\n", encoding="utf-8"
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path / "src"), *sys.path])
    catalog = PluginCatalog([PluginSource("tplkit", "tplkit_plugin:plugin", "entry_point")])
    monkeypatch.setattr(PluginCatalog, "default", staticmethod(lambda: catalog))
    target = tmp_path / "mini-app"
    result = runner.invoke(app, ["init", str(target), "-t", "tplkit.mini"])
    assert result.exit_code == 0, result.output
    assert (target / "harness.yaml").read_text(encoding="utf-8") == "metadata: { name: mini-app }\n"
    missing = runner.invoke(app, ["init", str(target), "-t", "tplkit.other", "--force"])
    assert "plugin 'tplkit' has no template 'other'" in missing.output
    assert hw.Plugin  # the plugin used the public API only


def test_the_rendered_project_passes_its_own_tests(project: Path) -> None:
    """RULES T6, through ``harnessweaver test``: offline, test mode on."""
    result = runner.invoke(app, ["test", "-q", "-p", "no:cacheprovider"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("template", [t for t in BUILTIN_TEMPLATES if t != "extraction"])
def test_every_template_passes_its_own_tests(
    template: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RULES T6 for each built-in template: render it, then run its tests offline."""
    root = tmp_path / f"demo-{template}"
    assert runner.invoke(app, ["init", str(root), "-t", template]).exit_code == 0
    assert "__app_name__" not in "".join(
        (root / f).read_text(encoding="utf-8") for f in files(root)
    )
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["test", "-q", "-p", "no:cacheprovider"])
    assert result.exit_code == 0, result.output
    # Every template names its code "app"; this process must import this one's.
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name)
    validated = runner.invoke(app, ["spec", "validate", "--env", "offline"])
    assert validated.exit_code == 0, validated.output
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]


def test_scaffolds_arent_templates(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "x"), "-t", "_plugin"])
    assert result.exit_code == 1
    assert "no template '_plugin'" in result.output


def test_test_passes_pytest_failures_through(project: Path) -> None:
    (project / "tests" / "test_fails.py").write_text(
        "def test_fails() -> None:\n    raise AssertionError\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["test", "-q", "-p", "no:cacheprovider", "tests/test_fails.py"])
    assert result.exit_code == 1
