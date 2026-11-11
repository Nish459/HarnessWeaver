"""The ``workflow`` runner: a deterministic step DAG (DESIGNS No. 15).

```yaml
runner:
  use: workflow
  output: report
  steps:
    - { id: extract,   handler: "app.flow:extract" }
    - { id: classify,  handler: "app.flow:classify",  needs: [extract] }
    - { id: summarize, handler: "app.flow:summarize", needs: [extract] }
    - { id: report,    handler: "app.flow:draft",     needs: [classify, summarize],
        evaluator: "app.flow:review", max_rounds: 3 }
```

* A step runs when everything it ``needs`` has finished; steps that are ready
  together run in parallel.
* A handler is ``async (session, inputs) -> output``. ``inputs`` holds the run's
  ``input`` and the outputs of the steps it needs, by id.
* With an ``evaluator`` (``async (session, output) -> True | False | "feedback"``),
  the step is an evaluator-optimizer loop: the handler runs again with
  ``inputs["feedback"]`` and ``inputs["round"]`` until the evaluator accepts or
  ``max_rounds`` is reached; then ``on_reject`` decides.

There is no planning: the graph is fixed by the spec (R12). Finished steps are
checkpointed, so after an approval only the interrupted step runs again.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Self

import anyio
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from harnessweaver._imports import import_object
from harnessweaver.core.context import RunContext
from harnessweaver.core.errors import (
    HarnessError,
    RunBlocked,
    RunEscalated,
    RunInterrupted,
    RunSuspended,
)
from harnessweaver.core.plugins import runner
from harnessweaver.runners._output import to_json
from harnessweaver.runners.direct import ALL_HOOKS
from harnessweaver.session import Session

__all__ = ["WorkflowConfig", "WorkflowRunner", "WorkflowStep"]

type Handler = Callable[[Session, dict[str, Any]], Awaitable[Any]]
type Evaluator = Callable[[Session, Any], Awaitable[bool | str]]


class WorkflowStep(BaseModel):
    """One step of a workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    handler: str = Field(description="'package.module:function' taking (session, inputs).")
    needs: tuple[str, ...] = ()
    evaluator: str | None = Field(
        default=None, description="'package.module:function' taking (session, output)."
    )
    max_rounds: int = Field(default=3, ge=1, le=20)
    on_reject: Literal["escalate", "block", "accept"] = Field(
        default="escalate", description="What happens when the evaluator never accepts."
    )


class WorkflowConfig(BaseModel):
    """Settings for ``runner: {use: workflow, ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: tuple[WorkflowStep, ...] = Field(min_length=1)
    output: str | None = Field(default=None, description="The step whose output is the result.")

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        for step in self.steps:
            unknown = [n for n in step.needs if n not in ids]
            if unknown:
                raise ValueError(f"step {step.id} needs unknown step(s): {', '.join(unknown)}")
        if self.output is not None and self.output not in ids:
            raise ValueError(f"output {self.output!r} is not a step")
        done: set[str] = set()
        while len(done) < len(ids):
            ready = [s.id for s in self.steps if s.id not in done and set(s.needs) <= done]
            if not ready:
                stuck = sorted(set(ids) - done)
                raise ValueError(f"the steps form a cycle: {', '.join(stuck)}")
            done.update(ready)
        return self


def _first(group: BaseExceptionGroup[BaseException]) -> BaseException:
    """The error that should end the run, from a parallel group: the most severe one."""
    leaves: list[BaseException] = []

    def walk(error: BaseException) -> None:
        if isinstance(error, BaseExceptionGroup):
            for inner in error.exceptions:  # pyright: ignore[reportUnknownVariableType]
                walk(inner)  # pyright: ignore[reportUnknownArgumentType]
        else:
            leaves.append(error)

    walk(group)
    for kind in (RunBlocked, RunSuspended, RunEscalated, RunInterrupted, HarnessError, Exception):
        for error in leaves:
            if isinstance(error, kind):
                return error
    return leaves[0]


@runner(
    "workflow",
    reaches=ALL_HOOKS,
    config=WorkflowConfig,
    sample={"steps": [{"id": "echo", "handler": "harnessweaver.testing.samples:echo_step"}]},
)
class WorkflowRunner:
    """Run a fixed graph of app functions, in parallel where the graph allows."""

    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        self.handlers: dict[str, Handler] = {
            s.id: import_object(s.handler, f"steps[{s.id}].handler") for s in config.steps
        }
        self.evaluators: dict[str, Evaluator] = {
            s.id: import_object(s.evaluator, f"steps[{s.id}].evaluator")
            for s in config.steps
            if s.evaluator is not None
        }

    async def execute(
        self, ctx: RunContext, input: Any, resume: Mapping[str, JsonValue] | None
    ) -> Any:
        raw = resume.get("completed") if resume else None
        completed: dict[str, JsonValue] = dict(raw) if isinstance(raw, dict) else {}
        # Keep the finished steps if this pass suspends before another step finishes.
        ctx.set_resume_point({"completed": dict(completed)})
        remaining = [s for s in self.config.steps if s.id not in completed]

        async def run_step(step: WorkflowStep) -> None:
            inputs: dict[str, Any] = {"input": input, **{n: completed[n] for n in step.needs}}
            output = await self._step(ctx, step, inputs)
            completed[step.id] = to_json(output)
            # Run-wide settle, so a parallel step still running may ask a human
            # again about a call it repeats; per-step grants if that ever matters.
            ctx.settle_grants()
            ctx.set_resume_point({"completed": dict(completed)})

        while remaining:
            ready = [s for s in remaining if all(n in completed for n in s.needs)]
            if len(ready) == 1:
                await run_step(ready[0])
            else:
                try:
                    async with anyio.create_task_group() as group:
                        for step in ready:
                            group.start_soon(run_step, step)
                except BaseExceptionGroup as errors:
                    raise _first(errors) from None
            remaining = [s for s in remaining if s.id not in completed]
        return completed[self.config.output or self.config.steps[-1].id]

    async def _step(self, ctx: RunContext, step: WorkflowStep, inputs: dict[str, Any]) -> Any:
        session = Session.for_run(ctx, step=step.id)
        handler = self.handlers[step.id]
        evaluator = self.evaluators.get(step.id)
        if evaluator is None:
            return await handler(session, inputs)
        feedback: str | None = None
        output: Any = None
        for round_ in range(step.max_rounds):
            output = await handler(session, {**inputs, "feedback": feedback, "round": round_})
            verdict = await evaluator(session, output)
            accepted = verdict is True
            ctx.trace.note(
                f"workflow.{step.id}",
                "accepted" if accepted else "rejected",
                details={"round": round_},
            )
            if accepted:
                return output
            feedback = verdict if isinstance(verdict, str) else None
        reason = f"step {step.id} wasn't accepted after {step.max_rounds} round(s)"
        if step.on_reject == "accept":
            return output
        if step.on_reject == "block":
            raise RunBlocked(reason, code="workflow_rejected")
        raise RunEscalated(reason, code="workflow_rejected")
