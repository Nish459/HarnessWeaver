"""``harnessweaver tools pin``: pin each tool manifest's definition (S2, ADR-0028).

A pin is the ``definition_digest`` of what a model is told about a tool (its
name, description and input schema). The governor blocks a tool whose
definition no longer matches its pin, so a changed tool can't slip into
production unreviewed (rug-pull defense). Pin after reviewing a change.
"""

from typing import Annotated

import typer
from ruamel.yaml.comments import CommentedMap

from harnessweaver.core.errors import HarnessError
from harnessweaver.modules.tools import load_manifest, manifest_files
from harnessweaver.spec import load_spec
from harnessweaver_cli import _yaml
from harnessweaver_cli._load import fail, spec_path
from harnessweaver_cli.spec import Env, Path_, ProfileDirs

__all__ = ["tools_app"]

tools_app = typer.Typer(help="Work with tool manifests.", no_args_is_help=True)


def _pin(spec: CommentedMap, digest: str) -> None:
    """Set ``definition_digest`` right after ``input_schema``, where a reader looks for it."""
    keys = list(spec)
    if "definition_digest" in spec:
        spec["definition_digest"] = digest
    elif "input_schema" in spec:
        spec.insert(keys.index("input_schema") + 1, "definition_digest", digest)
    else:
        spec["definition_digest"] = digest


@tools_app.command("pin")
def pin(
    path: Path_ = None,
    names: Annotated[
        list[str] | None, typer.Option("--tool", help="Pin only this tool; repeatable.")
    ] = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
) -> None:
    """Write each manifest's current ``definition_digest`` into it, comments kept."""
    target = spec_path(path)
    try:
        effective = load_spec(target, env=env, profile_dirs=profile_dir or [])
        globs = effective.spec.tools.manifests
        if not globs:
            raise fail("the spec has no tools.manifests to pin")
        files = manifest_files(globs, target.resolve().parent)
        manifests = [(file, load_manifest(file)) for file in files]
    except HarnessError as exc:
        raise fail(exc) from None
    wanted = set(names or [])
    unknown = wanted - {m.name for _, m in manifests}
    if unknown:
        raise fail(f"no manifest for {', '.join(sorted(unknown))}")
    for file, manifest in manifests:
        if wanted and manifest.name not in wanted:
            continue
        pinned, computed = manifest.spec.definition_digest, manifest.computed_digest()
        if pinned == computed:
            typer.echo(f"ok      {manifest.name} is pinned")
            continue
        document = _yaml.read(file)
        _pin(document["spec"], computed)
        _yaml.write(file, document)
        verb = "pinned" if pinned is None else "re-pinned"
        typer.echo(f"{verb:<7} {manifest.name}: {computed}")
