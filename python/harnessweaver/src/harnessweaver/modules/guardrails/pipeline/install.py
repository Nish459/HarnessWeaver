"""Installing the spec's guards on the hook bus, banded by the layer that declared them."""

from collections.abc import Sequence

from harnessweaver.core.bus import HookBus
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import (
    Band,
)
from harnessweaver.core.middleware import Registration
from harnessweaver.core.registry import Registry
from harnessweaver.modules.guardrails.pipeline.guards import LAYER_BANDS, STAGE_HOOKS, Guard, Stage
from harnessweaver.modules.guardrails.pipeline.handlers import guard_handler
from harnessweaver.spec.loader import EffectiveSpec
from harnessweaver.spec.models import GuardrailsSpec, GuardSpec, HarnessSpec

__all__ = ["configured_guards", "install_guardrails"]


def _band(effective: EffectiveSpec, path: str) -> Band:
    # Provenance is kept per value; the layer that set the item's id declared it.
    origin = effective.origin(f"{path}.id") or effective.origin(f"{path}.use")
    return LAYER_BANDS[origin.kind] if origin is not None else Band.APP


def _guard(item: GuardSpec, index: int, stage: Stage, registry: Registry, prefix: str) -> Guard:
    info = registry.provider("Guardrail", item.use)
    if info.stages and stage not in info.stages:
        raise SpecError(
            f"guard {item.use} can't run at stage {stage!r}; it supports {', '.join(info.stages)}"
        )
    if item.where != "local":
        raise SpecError(f"guard {item.id or item.use}: where: {item.where} needs the sidecar")
    guard_id = item.id or f"{item.use}#{index + 1}"
    return Guard(
        id=guard_id,
        name=f"{prefix}.{stage}[{guard_id}]",
        provider=info.build(item.provider_settings()),
        action=item.action,
        mode=item.mode,
        fail_mode=item.fail_mode,
        timeout=item.timeout,
    )


def _groups(items: Sequence[tuple[GuardSpec, Band]]) -> list[list[tuple[GuardSpec, Band]]]:
    groups: list[list[tuple[GuardSpec, Band]]] = []
    for item, band in items:
        last = groups[-1] if groups else None
        if item.parallel and last and last[-1][0].parallel and last[-1][1] is band:
            last.append((item, band))
        else:
            groups.append([(item, band)])
    return groups


def _sections(spec: HarnessSpec) -> list[tuple[str | None, str, GuardrailsSpec]]:
    found: list[tuple[str | None, str, GuardrailsSpec]] = [(None, "guardrails", spec.guardrails)]
    found += [
        (name, f"tasks.{name}.guardrails", task.guardrails)
        for name, task in spec.tasks.items()
        if task.guardrails is not None
    ]
    return found


def configured_guards(spec: HarnessSpec) -> list[tuple[str, GuardSpec]]:
    """Every enabled guard with its full name (``guardrails.input[pii]``), as traces,
    ``doctor`` and eval reports name it."""
    return [
        (f"{prefix}.{stage}[{item.id or f'{item.use}#{index + 1}'}]", item)
        for _, prefix, section in _sections(spec)
        for stage in STAGE_HOOKS
        for index, item in enumerate(i for i in getattr(section, stage) if i.enabled)
    ]


def install_guardrails(effective: EffectiveSpec, registry: Registry, bus: HookBus) -> int:
    """Turn every enabled guard into middleware. Returns how many middleware were added.

    Raises:
        SpecError: For an unknown provider, a stage it doesn't support, a guard
            that needs the sidecar, or a baseline guard that fails open (R2).
    """
    added = 0
    for task, prefix, section in _sections(effective.spec):
        for stage, hook in STAGE_HOOKS.items():
            items = [item for item in getattr(section, stage) if item.enabled]
            banded = [
                (item, Band.TASK if task else _band(effective, f"{prefix}.{stage}[{item.id}]"))
                for item in items
            ]
            for group in _groups(banded):
                guards = [
                    _guard(item, items.index(item), stage, registry, prefix) for item, _ in group
                ]
                ids = "+".join(g.id for g in guards)
                label = f"{prefix}.{stage}[{ids}]"
                closed = any(g.fail_mode == "closed" for g in guards)
                single = guards[0] if len(guards) == 1 else None
                bus.add(
                    Registration(
                        name=label,
                        handler=guard_handler(stage, guards, label),
                        hooks=frozenset({hook}),
                        band=group[0][1],
                        fail_mode=single.fail_mode if single else ("closed" if closed else "open"),
                        timeout=single.timeout if single else None,
                        tasks=frozenset({task}) if task else None,
                    )
                )
                added += 1
    return added
