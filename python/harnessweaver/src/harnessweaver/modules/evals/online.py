"""Online evals: sample production runs at ``run.end`` and grade them (DESIGNS No. 23).

``evals.online.sample_rate`` picks runs by their id (:func:`sampled`), so every
process agrees. A sampled run's guard firings and grades are kept in the state
store as an ``OnlineSample`` that names the run instead of copying its content.
Only deterministic graders run online: a judge's latency and cost don't belong
in a production run, and online samples have no ``expect``. Sampling is
observability, not a control, so it fails open.
"""

from collections.abc import Mapping

from pydantic import JsonValue

from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope, SystemClock
from harnessweaver.core.errors import SpecError
from harnessweaver.core.evals import EvalSample, GraderResult, OnlineSample, parse_graders
from harnessweaver.core.hooks import Band, HookPoint, RunEndEvent
from harnessweaver.core.middleware import Registration
from harnessweaver.core.ports import StateStore
from harnessweaver.core.registry import Registry
from harnessweaver.modules.evals.datasets import build_grader
from harnessweaver.modules.evals.results import firings, sampled
from harnessweaver.spec.models import HarnessSpec

__all__ = ["install_online_evals"]


def install_online_evals(
    spec: HarnessSpec,
    registry: Registry,
    bus: HookBus,
    state: StateStore,
    schemas: Mapping[str, dict[str, JsonValue] | None],
) -> bool:
    """Install the ``evals.online`` middleware when the spec samples runs.

    Raises:
        SpecError: For a grader that isn't deterministic, or bad grader settings.
    """
    online = spec.evals.online
    if online is None or online.sample_rate <= 0:
        return False
    graders = []
    for grader in parse_graders(online.graders):
        if not registry.provider("Evaluator", grader.use).deterministic:
            raise SpecError(
                f"evals.online.graders: {grader.label} isn't deterministic; grade with it "
                "offline (harnessweaver eval run)"
            )
        graders.append((grader, build_grader(registry, grader)))
    rate = online.sample_rate

    async def sample(event: RunEndEvent, env: Envelope) -> None:
        if not sampled(env.run_id, rate):
            return
        ctx = current_run()
        guards = firings(ctx.trace.events if ctx is not None else ())
        seen = EvalSample(
            task=env.task,
            output=event.output,
            status=event.status,
            error_code=event.error.code if event.error is not None else None,
            guards=guards,
            output_schema=schemas.get(env.task or ""),
        )
        grades = []
        for grader, evaluator in graders:
            grade = await evaluator.grade(seen)
            grades.append(GraderResult(grader=grader.label, **grade.model_dump()))
        clock = ctx.clock if ctx is not None else SystemClock()
        await state.put_sample(
            OnlineSample(
                run_id=env.run_id,
                task=env.task,
                tenant=env.tenant,
                at=clock.now(),
                status=event.status,
                grades=tuple(grades),
                guards=guards,
            )
        )

    bus.add(
        Registration(
            name="evals.online",
            handler=sample,  # pyright: ignore[reportArgumentType]
            hooks=frozenset({HookPoint.RUN_END}),
            band=Band.PLATFORM,
            fail_mode="open",
        )
    )
    return True
