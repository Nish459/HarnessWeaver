"""The guardrails pipeline: the spec's guards become middleware on hook points (DESIGNS No. 20).

| Stage         | Hook point      | Content checked                          |
| ------------- | --------------- | ---------------------------------------- |
| `input`       | `input.before`  | every string in the input                |
| `context`     | `context.after` | each retrieved item; `block` drops it    |
| `tool_result` | `tool.after`    | every string in the tool's output        |
| `output`      | `output.before` | every string in the candidate output     |
| `stream`      | `stream.chunk`  | each streamed chunk                      |

Semantics (fixtures suite ``guards``):

* Guards run in list order, baseline items first. Each guard is one middleware,
  so redactions chain and the most severe answer wins (No. 8).
* A provider proposes an action; the spec's ``action`` overrides it whenever the
  provider flags something. Asking to redact what a provider can't redact blocks.
* ``mode: log_only`` (or ``action: log_only``) records what the guard would have
  done and lets the content through (R8).
* Consecutive ``parallel: true`` guards in one band run concurrently as a group.
  Their redactions are then applied in list order, each guard re-checking the
  content the previous one redacted.
* The band comes from the layer that declared the guard: org profiles ->
  ``baseline``, built-in profiles -> ``platform``, the app -> ``app``, a task's
  own guards -> ``task``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Literal

import anyio
from pydantic import JsonValue

from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.guards import GuardAction, GuardResult
from harnessweaver.core.hooks import (
    Band,
    ContextEvent,
    HookPoint,
    InputEvent,
    OutputEvent,
    StreamChunkEvent,
    ToolResultEvent,
)
from harnessweaver.core.middleware import FailMode, Handler, Registration
from harnessweaver.core.outcomes import Block, Continue, Escalate, Outcome, Retry, Suspend
from harnessweaver.core.ports import Guardrail
from harnessweaver.core.registry import Registry
from harnessweaver.spec.loader import EffectiveSpec
from harnessweaver.spec.merge import LayerKind
from harnessweaver.spec.models import GuardrailsSpec, GuardSpec

__all__ = [
    "LAYER_BANDS",
    "STAGE_HOOKS",
    "Guard",
    "Verdict",
    "check",
    "guard_handler",
    "install_guardrails",
]

type Stage = Literal["input", "context", "tool_result", "output", "stream"]

STAGE_HOOKS: Final[dict[Stage, HookPoint]] = {
    "input": HookPoint.INPUT_BEFORE,
    "context": HookPoint.CONTEXT_AFTER,
    "tool_result": HookPoint.TOOL_AFTER,
    "output": HookPoint.OUTPUT_BEFORE,
    "stream": HookPoint.STREAM_CHUNK,
}

_RANK: Final[dict[GuardAction, int]] = {
    GuardAction.ALLOW: 0,
    GuardAction.LOG_ONLY: 0,
    GuardAction.REDACT: 1,
    GuardAction.REPAIR: 2,
    GuardAction.ESCALATE: 3,
    GuardAction.REQUIRE_APPROVAL: 4,
    GuardAction.BLOCK: 5,
}

LAYER_BANDS: Final[dict[LayerKind, Band]] = {
    LayerKind.ORG: Band.BASELINE,
    LayerKind.DEFAULTS: Band.PLATFORM,
    LayerKind.PROFILE: Band.PLATFORM,
    LayerKind.APP: Band.APP,
    LayerKind.OVERLAY: Band.APP,
}


@dataclass(frozen=True, slots=True)
class Guard:
    """One configured guard."""

    id: str
    provider: Guardrail
    action: GuardAction | None = None
    mode: Literal["enforce", "log_only"] = "enforce"
    fail_mode: FailMode = "closed"
    timeout: timedelta | None = None

    @property
    def shadow(self) -> bool:
        return self.mode == "log_only" or self.action is GuardAction.LOG_ONLY


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one guard decided about a list of texts."""

    action: GuardAction
    texts: tuple[str, ...]
    reason: str | None = None
    findings: tuple[str, ...] = ()


async def check(guard: Guard, texts: Sequence[str], env: Envelope) -> Verdict:
    """Run ``guard`` over every text and combine the answers; the most severe wins."""
    ctx = current_run()
    telemetry = ctx.telemetry if ctx is not None else None
    if telemetry is None:
        return await _check(guard, texts, env)
    with telemetry.guard_span(guard.id, None, guard.mode) as span:
        verdict = await _check(guard, texts, env)
        telemetry.guard_done(span, verdict.action.value, list(verdict.findings))
        return verdict


async def _check(guard: Guard, texts: Sequence[str], env: Envelope) -> Verdict:
    worst = GuardAction.ALLOW
    out = list(texts)
    reason: str | None = None
    found: set[str] = set()
    for index, text in enumerate(texts):
        result = await guard.provider.check(text, env)
        if not isinstance(result, GuardResult):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"guard {guard.id} returned {type(result).__name__}")
        action = result.action
        if action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
            continue
        if guard.action is not None and guard.action is not GuardAction.LOG_ONLY:
            action = guard.action
        if action is GuardAction.REDACT:
            if result.content is None:
                action = GuardAction.BLOCK
                reason = reason or f"{result.reason or 'flagged'} (it can't be redacted)"
            else:
                out[index] = result.content
        found.update(f.type for f in result.findings)
        reason = reason or result.reason
        if _RANK[action] > _RANK[worst]:
            worst = action
    return Verdict(worst, tuple(out), reason, tuple(sorted(found)))


def _outcome(label: str, verdict: Verdict, stage: Stage, rebuilt: Any) -> Outcome:
    reason = f"{label}: {verdict.reason or verdict.action.value}"
    match verdict.action:
        case GuardAction.ALLOW | GuardAction.LOG_ONLY:
            return Continue()
        case GuardAction.REDACT:
            return Continue(modified=rebuilt, note=reason)
        case GuardAction.REPAIR if stage == "output":
            return Retry(reason=reason)
        case GuardAction.ESCALATE:
            return Escalate(reason=reason)
        case GuardAction.REQUIRE_APPROVAL:
            return Suspend(reason=reason)
        case _:
            return Block(reason=reason, code="guard_blocked")


def _shadow(label: str, verdict: Verdict) -> Outcome:
    if verdict.action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
        return Continue()
    return Continue(
        note=f"would {verdict.action.value}: {label}: {verdict.reason or ''}".rstrip(": ")
    )


# --- content access ------------------------------------------------------------------------------

type Path = tuple[str | int, ...]


def _leaves(value: JsonValue, path: Path = ()) -> list[tuple[Path, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        return [leaf for i, item in enumerate(value) for leaf in _leaves(item, (*path, i))]
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in _leaves(item, (*path, key))]
    return []


def _replace(value: JsonValue, changes: dict[Path, str], path: Path = ()) -> JsonValue:
    if path in changes:
        return changes[path]
    if isinstance(value, list):
        return [_replace(item, changes, (*path, i)) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _replace(item, changes, (*path, key)) for key, item in value.items()}
    return value


def _content(stage: Stage, event: Any) -> tuple[list[str], Callable[[Sequence[str]], Any]]:
    """The texts a stage checks, and how to rebuild the event from redacted texts."""
    if stage == "stream":
        chunk_event: StreamChunkEvent = event

        def rebuild_chunk(texts: Sequence[str]) -> Any:
            chunk = chunk_event.chunk.model_copy(update={"delta": texts[0]})
            return chunk_event.model_copy(update={"chunk": chunk})

        return [chunk_event.chunk.delta], rebuild_chunk
    if stage == "tool_result":
        result_event: ToolResultEvent = event
        root: JsonValue = result_event.result.output

        def wrap(value: JsonValue) -> Any:
            result = result_event.result.model_copy(update={"output": value})
            return result_event.model_copy(update={"result": result})

    elif stage == "input":
        input_event: InputEvent = event
        root = input_event.input

        def wrap(value: JsonValue) -> Any:
            return input_event.model_copy(update={"input": value})

    else:
        output_event: OutputEvent = event
        root = output_event.output

        def wrap(value: JsonValue) -> Any:
            return output_event.model_copy(update={"output": value})

    leaves = _leaves(root)
    paths = [path for path, _ in leaves]

    def rebuild(texts: Sequence[str]) -> Any:
        return wrap(_replace(root, dict(zip(paths, texts, strict=True))))

    return [text for _, text in leaves], rebuild


# --- handlers ------------------------------------------------------------------------------------


async def _member(guard: Guard, texts: Sequence[str], env: Envelope) -> Verdict:
    """A parallel group member, with its own timeout and fail mode."""
    try:
        with anyio.fail_after(guard.timeout.total_seconds() if guard.timeout else None):
            return await check(guard, texts, env)
    except Exception as exc:
        reason = f"guard failed ({type(exc).__name__})"
        ctx = current_run()
        if ctx is not None:
            ctx.trace.note(f"guard:{guard.id}", reason, code="guard_error")
        if guard.fail_mode == "open":
            return Verdict(GuardAction.ALLOW, tuple(texts))
        return Verdict(GuardAction.BLOCK, tuple(texts), reason)


async def _group(
    guards: Sequence[Guard], texts: Sequence[str], env: Envelope
) -> tuple[Verdict, list[str]]:
    verdicts: list[Verdict | None] = [None] * len(guards)

    async def run(index: int) -> None:
        verdicts[index] = await _member(guards[index], texts, env)

    async with anyio.create_task_group() as group:
        for index in range(len(guards)):
            group.start_soon(run, index)
    done = [v for v in verdicts if v is not None]
    notes = [
        f"would {v.action.value}: {g.id}"
        for g, v in zip(guards, done, strict=True)
        if g.shadow and v.action not in (GuardAction.ALLOW, GuardAction.LOG_ONLY)
    ]
    enforced = [(g, v) for g, v in zip(guards, done, strict=True) if not g.shadow]
    worst = Verdict(GuardAction.ALLOW, tuple(texts))
    for _, verdict in enforced:
        if _RANK[verdict.action] > _RANK[worst.action]:
            worst = verdict
    if worst.action is GuardAction.REDACT:
        current = list(texts)
        for guard, verdict in enforced:
            if verdict.action is GuardAction.REDACT:
                again = await _member(guard, current, env)
                if again.action is GuardAction.REDACT:
                    current = list(again.texts)
        worst = Verdict(GuardAction.REDACT, tuple(current), worst.reason, worst.findings)
    return worst, notes


def guard_handler(stage: Stage, guards: Sequence[Guard], label: str) -> Handler:
    """The middleware for one guard, or one parallel group of guards."""
    if not guards:
        raise ValueError("a guard handler needs at least one guard")

    async def handle(event: Any, env: Envelope) -> Outcome | None:
        if stage == "context":
            return await _context(event, env, guards, label)
        texts, rebuild = _content(stage, event)
        if not texts:
            return None
        if len(guards) == 1:
            verdict = await check(guards[0], texts, env)
            if guards[0].shadow:
                return _shadow(label, verdict)
            return _outcome(label, verdict, stage, rebuild(verdict.texts))
        verdict, notes = await _group(guards, texts, env)
        outcome = _outcome(label, verdict, stage, rebuild(verdict.texts))
        if notes and isinstance(outcome, Continue):
            return Continue(modified=outcome.modified, note="; ".join(notes))
        return outcome

    return handle


async def _context(
    event: ContextEvent, env: Envelope, guards: Sequence[Guard], label: str
) -> Outcome | None:
    kept = []
    dropped = 0
    changed = False
    notes: list[str] = []
    for item in event.items:
        content = item.content
        drop = False
        for guard in guards:
            verdict = await check(guard, [content], env)
            if verdict.action in (GuardAction.ALLOW, GuardAction.LOG_ONLY):
                continue
            if guard.shadow:
                notes.append(f"would {verdict.action.value}: {guard.id}")
                continue
            if verdict.action is GuardAction.REDACT:
                content = verdict.texts[0]
            elif verdict.action in (GuardAction.BLOCK, GuardAction.REPAIR):
                drop = True
                break
            else:
                return _outcome(label, verdict, "context", None)
        if drop:
            dropped += 1
            continue
        if content != item.content:
            changed = True
            kept.append(item.model_copy(update={"content": content}))
        else:
            kept.append(item)
    if dropped:
        notes.append(f"dropped {dropped} item(s)")
    note = "; ".join(notes) or None
    if dropped or changed:
        return Continue(modified=event.model_copy(update={"items": tuple(kept)}), note=note)
    return Continue(note=note)


# --- installing ----------------------------------------------------------------------------------


def _band(effective: EffectiveSpec, path: str) -> Band:
    # Provenance is kept per value; the layer that set the item's id declared it.
    origin = effective.origin(f"{path}.id") or effective.origin(f"{path}.use")
    return LAYER_BANDS[origin.kind] if origin is not None else Band.APP


def _guard(item: GuardSpec, index: int, stage: Stage, registry: Registry) -> Guard:
    info = registry.provider("Guardrail", item.use)
    if info.stages and stage not in info.stages:
        raise SpecError(
            f"guard {item.use} can't run at stage {stage!r}; it supports {', '.join(info.stages)}"
        )
    if item.where != "local":
        raise SpecError(f"guard {item.id or item.use}: where: {item.where} needs the sidecar")
    return Guard(
        id=item.id or f"{item.use}#{index + 1}",
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


def install_guardrails(effective: EffectiveSpec, registry: Registry, bus: HookBus) -> int:
    """Turn every enabled guard into middleware. Returns how many middleware were added.

    Raises:
        SpecError: For an unknown provider, a stage it doesn't support, a guard
            that needs the sidecar, or a baseline guard that fails open (R2).
    """
    spec = effective.spec
    sections: list[tuple[str | None, str, GuardrailsSpec]] = [(None, "guardrails", spec.guardrails)]
    sections += [
        (name, f"tasks.{name}.guardrails", task.guardrails)
        for name, task in spec.tasks.items()
        if task.guardrails is not None
    ]
    added = 0
    for task, prefix, section in sections:
        for stage, hook in STAGE_HOOKS.items():
            items = [item for item in getattr(section, stage) if item.enabled]
            banded = [
                (item, Band.TASK if task else _band(effective, f"{prefix}.{stage}[{item.id}]"))
                for item in items
            ]
            for group in _groups(banded):
                guards = [_guard(item, items.index(item), stage, registry) for item, _ in group]
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
