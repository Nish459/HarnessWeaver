"""Reading eval datasets and building their graders (DESIGNS No. 23)."""

from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from harnessweaver.core.errors import SpecError
from harnessweaver.core.evals import EvalDataset, GraderSpec
from harnessweaver.core.ports import Evaluator
from harnessweaver.core.registry import Registry
from harnessweaver.spec.yaml import load_yaml_file

__all__ = ["build_grader", "build_graders", "load_dataset", "read_dataset"]


def _problems(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '(dataset)'}: {e['msg']}" for e in exc.errors()
    )


def read_dataset(document: object, source: str) -> EvalDataset:
    """Validate a dataset document.

    Raises:
        SpecError: Naming ``source`` and the problems.
    """
    try:
        return EvalDataset.model_validate(document)
    except ValidationError as exc:
        raise SpecError(f"{source}: {_problems(exc)}") from None


def load_dataset(path: Path) -> EvalDataset:
    """Read a dataset file (YAML or JSON).

    Raises:
        SpecError: For a file that can't be read or isn't a valid dataset.
    """
    if not path.is_file():
        raise SpecError(f"no eval dataset at {path}")
    return read_dataset(load_yaml_file(path), str(path))


def build_grader(registry: Registry, spec: GraderSpec) -> Evaluator:
    """The ``Evaluator`` a grader names, built from its settings. A single setting fills
    the field the config's ``SHORTHAND`` names.

    Raises:
        UnknownProvider: For a grader no plugin provides.
        SpecError: For settings the grader doesn't accept.
    """
    info = registry.provider("Evaluator", spec.use)
    settings = spec.settings
    if settings is None:
        config: object = {}
    elif isinstance(settings, dict):
        config = settings
    else:
        key = getattr(info.config, "SHORTHAND", None) if info.config is not None else None
        if key is None:
            raise SpecError(f"grader {spec.label}: {spec.use} takes no single setting")
        config = {key: settings}
    try:
        return info.build(config)  # pyright: ignore[reportArgumentType]
    except SpecError as exc:
        raise SpecError(f"grader {spec.label}: {exc.message}") from None


def build_graders(
    registry: Registry, specs: Sequence[GraderSpec]
) -> list[tuple[GraderSpec, Evaluator]]:
    """Build each grader (see :func:`build_grader`)."""
    return [(spec, build_grader(registry, spec)) for spec in specs]
