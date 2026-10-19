"""Loading ``tools.manifests`` and checking every manifest when the harness loads (S2, R4)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from harnessweaver.core.errors import ExpressionSyntaxError, SpecError
from harnessweaver.core.expr import Expression, compile_expression
from harnessweaver.core.jsonschema import SchemaError, check_schema
from harnessweaver.core.manifests import ToolManifest
from harnessweaver.core.policy import TOOL_POLICY_VARIABLES
from harnessweaver.spec.yaml import load_yaml_file

__all__ = ["approval_rules", "load_manifests"]


def _paths(patterns: Sequence[str], base: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        if Path(pattern).is_absolute():
            matches = sorted(Path(Path(pattern).anchor).glob(pattern.lstrip("/")))
        else:
            matches = sorted(base.glob(pattern))
        files = [path for path in matches if path.is_file()]
        if not files:
            raise SpecError(f"tools.manifests: no file matches {pattern!r} under {base}")
        found += [path for path in files if path not in found]
    return found


def _resolve_schema(document: dict[str, Any], path: Path) -> None:
    spec = document.get("spec")
    schema = spec.get("input_schema") if isinstance(spec, dict) else None
    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if isinstance(ref, str) and not ref.startswith("#") and len(schema) == 1:  # type: ignore[arg-type]
        target = path.parent / ref
        if not target.is_file():
            raise SpecError(f"{path}: spec.input_schema.$ref: no file {ref!r}")
        loaded = load_yaml_file(target)
        if not isinstance(loaded, dict):
            raise SpecError(f"{target} must hold a JSON Schema object")
        spec["input_schema"] = loaded  # type: ignore[index]


def _problems(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in error['loc']) or '(document)'}: {error['msg']}"
        for error in exc.errors()
    )


def load_manifests(patterns: Sequence[str], base: Path) -> list[ToolManifest]:
    """Read every ``kind: Tool`` file the globs match, relative to the spec's directory.

    A schema file named by ``input_schema: {$ref: path}`` is read relative to the
    manifest. Each schema must use only the supported keywords (ADR-0026), each
    ``approval.when`` must compile, and names must be unique.

    Raises:
        SpecError: Naming the file and the problem.
    """
    manifests: list[ToolManifest] = []
    seen: dict[str, Path] = {}
    for path in _paths(patterns, base):
        document = load_yaml_file(path)
        if not isinstance(document, dict) or document.get("kind") != "Tool":
            raise SpecError(f"{path} isn't a 'kind: Tool' manifest")
        _resolve_schema(document, path)  # pyright: ignore[reportUnknownArgumentType]
        try:
            manifest = ToolManifest.model_validate(document)
        except ValidationError as exc:
            raise SpecError(f"{path}: {_problems(exc)}") from None
        try:
            check_schema(manifest.spec.input_schema)
        except SchemaError as exc:
            raise SpecError(f"{path}: spec.input_schema.{exc}") from None
        if manifest.name in seen:
            raise SpecError(
                f"{path}: tool {manifest.name!r} is also defined in {seen[manifest.name]}"
            )
        seen[manifest.name] = path
        manifests.append(manifest)
    approval_rules(manifests)
    return manifests


def approval_rules(manifests: Sequence[ToolManifest]) -> dict[str, Expression]:
    """Compile each manifest's ``approval.when`` against the policy names.

    Raises:
        SpecError: For an expression that doesn't compile.
    """
    rules: dict[str, Expression] = {}
    for manifest in manifests:
        approval = manifest.spec.approval
        if approval is None or approval.when is None:
            continue
        try:
            rules[manifest.name] = compile_expression(approval.when, declared=TOOL_POLICY_VARIABLES)
        except ExpressionSyntaxError as exc:
            raise SpecError(f"tool {manifest.name}: spec.approval.when: {exc.message}") from None
    return rules
