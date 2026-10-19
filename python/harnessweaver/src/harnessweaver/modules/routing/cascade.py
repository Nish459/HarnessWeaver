"""The routing cascade: one ``route.decide`` middleware per router (DESIGNS No. 19, ADR-0029).

Stages run in order and the first confident answer wins:

* an ``exact`` answer is confident;
* a ``probabilistic`` answer is confident when its confidence reaches the stage's
  ``threshold`` (a stage without a threshold accepts any confidence);
* an answer that names something outside the router's options, or a stage that
  fails, counts as an abstention.

When no stage is confident the router's ``default`` is used; without one, the
run's ``decide`` abstains. Every stage's answer is a ``harness.routing`` trace
note, whether it won or not (R13).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import current_run
from harnessweaver.core.decisions import Decision, DecisionKind
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.hooks import Band, HookPoint, RouteEvent
from harnessweaver.core.middleware import Handler, Registration
from harnessweaver.core.outcomes import Continue, Outcome
from harnessweaver.core.ports import Decider
from harnessweaver.core.registry import Registry
from harnessweaver.modules.guardrails import LAYER_BANDS
from harnessweaver.modules.routing.stages import SemanticDecider
from harnessweaver.spec.loader import EffectiveSpec
from harnessweaver.spec.models import RouterSpec, RoutingStage

__all__ = ["Stage", "cascade_handler", "decide_in_cascade", "install_routing"]

_FILE_SETTINGS = ("file",)


@dataclass(frozen=True, slots=True)
class Stage:
    """One cascade stage: its label on the trace, its decider and its threshold."""

    label: str
    decider: Decider
    threshold: float | None = None

    def confident(self, decision: Decision) -> bool:
        if decision.kind is DecisionKind.ABSTAIN:
            return False
        if decision.kind is not DecisionKind.PROBABILISTIC or self.threshold is None:
            return True
        return (decision.confidence or 0.0) >= self.threshold


async def decide_in_cascade(
    router: str,
    stages: Sequence[Stage],
    options: Sequence[str],
    default: str | None,
    ask: Any,
    note: Any = None,
) -> Decision | None:
    """Run ``stages`` on a request (``ask(decider)`` returns the stage's answer).

    Returns the winning decision with its stage set, the default, or ``None``
    when every stage abstained and there is no default.
    """
    for stage in stages:
        try:
            decision: Decision = await ask(stage.decider)
        except Exception as exc:  # a broken stage abstains; the cascade goes on
            decision = Decision.abstain(reason=f"the stage failed ({type(exc).__name__})")
        if decision.choice is not None and decision.choice not in options:
            decision = Decision.abstain(reason="it chose something that isn't an option")
        won = stage.confident(decision)
        if note is not None:
            note(router, stage, decision, won)
        if won:
            return decision.model_copy(update={"stage": stage.label})
    if default is None:
        return None
    return Decision.default(default, reason="no stage was confident")


def _note(router: str, stage: Stage, decision: Decision, won: bool) -> None:
    ctx = current_run()
    if ctx is None:
        return
    details: dict[str, JsonValue] = {
        "router": router,
        "stage": stage.label,
        "kind": decision.kind.value,
        "won": won,
    }
    if decision.choice is not None:
        details["choice"] = decision.choice
    if decision.confidence is not None:
        details["confidence"] = decision.confidence
    if stage.threshold is not None:
        details["threshold"] = stage.threshold
    reason = decision.reason or decision.kind.value
    ctx.trace.note("harness.routing", reason, hook=HookPoint.ROUTE_DECIDE, details=details)


def cascade_handler(name: str, router: RouterSpec, stages: Sequence[Stage]) -> Handler:
    """Middleware that answers ``route.decide`` for router ``name``."""

    async def handle(event: RouteEvent, env: Envelope) -> Outcome | None:
        request = event.request
        if request.router != name or event.decision is not None:
            return None
        if not request.options:
            request = request.model_copy(update={"options": router.options})

        async def ask(decider: Decider) -> Decision:
            return await decider(request)

        decision = await decide_in_cascade(
            name, stages, request.options, router.default, ask, _note
        )
        if decision is None:
            return None
        return Continue(
            modified=event.model_copy(update={"request": request, "decision": decision})
        )

    return handle


def _stage(
    name: str, index: int, item: RoutingStage, router: RouterSpec, registry: Registry, base: Path
) -> Stage:
    where = f"routing.{name}.cascade[{item.id or index}]"
    info = registry.provider("Decider", item.use)
    settings = dict(item.provider_settings())
    for key in _FILE_SETTINGS:
        value = settings.get(key)
        if isinstance(value, str) and not Path(value).is_absolute():
            settings[key] = str(base / value)
    try:
        decider: Any = info.build(settings)
    except SpecError as exc:
        raise SpecError(f"{where}: {exc.message}") from None
    if isinstance(decider, SemanticDecider) and decider.config.encoder != "semantic.hashing":
        decider.bind_encoder(registry.provider("Embedder", decider.config.encoder).build({}))
    choices = getattr(decider, "choices", None)
    if isinstance(choices, set):
        unknown = sorted(str(c) for c in choices if c not in router.options)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if unknown:
            raise SpecError(f"{where}: {', '.join(unknown)} isn't one of the router's options")
    return Stage(label=item.id or item.use, decider=decider, threshold=item.threshold)


def install_routing(effective: EffectiveSpec, registry: Registry, bus: HookBus, base: Path) -> int:
    """Install one cascade per ``routing.<router>``, banded by the layer that declared it.

    Raises:
        SpecError: For an unknown stage, settings it rejects, or a stage that can
            choose something the router doesn't offer (R4).
    """
    for name, router in effective.spec.routing.items():
        stages = [
            _stage(name, index, item, router, registry, base)
            for index, item in enumerate(router.cascade)
        ]
        origin = effective.origin(f"routing.{name}.options")
        band = LAYER_BANDS[origin.kind] if origin is not None else Band.APP
        bus.add(
            Registration(
                name=f"routing.{name}",
                handler=cascade_handler(name, router, stages),
                hooks=frozenset({HookPoint.ROUTE_DECIDE}),
                band=band,
                fail_mode="closed",
            )
        )
    return len(effective.spec.routing)
