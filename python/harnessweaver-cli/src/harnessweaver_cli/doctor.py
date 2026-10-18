"""``harnessweaver doctor``: what a spec reaches and what to look at next.

Reports the adoption level, unreachable hook points (as load errors), duplicate
owners of retries (R5), unpinned profiles, guards still in shadow mode (R8),
content capture (R9) and plugin installation problems.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from harnessweaver import Harness
from harnessweaver.core.errors import HarnessError
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.spec import REQUIREMENTS, Level
from harnessweaver.spec.models import GuardrailsSpec, GuardSpec, HarnessSpec
from harnessweaver.spec.sources import parse_ref
from harnessweaver_cli._load import spec_path

__all__ = ["Finding", "diagnose", "doctor"]

type Severity = Literal["ok", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    check: str
    message: str


_STAGES = ("input", "context", "tool_result", "output", "stream")


def _named(prefix: str, guardrails: GuardrailsSpec) -> list[tuple[str, GuardSpec]]:
    # Labelled as the guardrails pipeline labels them, so doctor and traces agree.
    return [
        (f"{prefix}.{stage}[{guard.id or f'{guard.use}#{index + 1}'}]", guard)
        for stage in _STAGES
        for index, guard in enumerate(getattr(guardrails, stage))
    ]


def _guards(spec: HarnessSpec) -> list[tuple[str, GuardSpec]]:
    found = _named("guardrails", spec.guardrails)
    for name, task in spec.tasks.items():
        if task.guardrails is not None:
            found += _named(f"tasks.{name}.guardrails", task.guardrails)
    return found


def _level(harness: Harness) -> list[Finding]:
    report = harness.spec.level
    tier = harness.spec.spec.metadata.risk_tier
    level, required = report.level.value, report.required.value
    findings = [
        Finding("ok", "level", f"adoption level {level}; risk tier {tier!r} requires {required}")
    ]
    following = next((lvl for lvl in Level if lvl.rank == report.level.rank + 1), None)
    if following is not None:
        missing = [REQUIREMENTS[code] for code in report.missing_for(following)]
        if missing:
            findings.append(
                Finding("ok", "next level", f"to reach {following.value}: {'; '.join(missing)}")
            )
    return findings


def _owners(harness: Harness) -> list[Finding]:
    models = harness.spec.spec.models
    if models.provider is None:
        return []
    info = harness.registry.provider("ModelProvider", models.provider)
    settings: Any = models.provider_settings()
    config = info.config.model_validate(settings) if info.config is not None else None
    base_url = getattr(config, "base_url", None)
    retries = getattr(config, "max_retries", 0) or 0
    if base_url and retries > 0:
        return [
            Finding(
                "warn",
                "retries",
                f"{models.provider} retries {retries} time(s) behind the gateway at {base_url}; "
                "let the gateway own retries and set max_retries: 0 (R5)",
            )
        ]
    return [Finding("ok", "retries", "retries have one owner")]


def _pins(spec: HarnessSpec) -> list[Finding]:
    findings: list[Finding] = []
    for text in spec.extends:
        ref = parse_ref(text)
        plugin_profile = ref.scheme == "profile" and "." in ref.name
        if (ref.scheme == "org" or plugin_profile) and ref.range is None:
            findings.append(
                Finding("warn", "pins", f"{text} isn't pinned; use a range like {text}@^1 (V1)")
            )
    return findings or [Finding("ok", "pins", "every org and plugin profile is pinned")]


def _shadow(spec: HarnessSpec) -> list[Finding]:
    shadow = [
        name
        for name, g in _guards(spec)
        if g.mode == "log_only" or g.action is GuardAction.LOG_ONLY
    ]
    if not shadow:
        return [Finding("ok", "shadow guards", "no guards in shadow mode")]
    return [
        Finding(
            "warn",
            "shadow guards",
            f"{name} is in shadow mode; promote it to enforce once evals back it (R8)",
        )
        for name in shadow
    ]


def _content(spec: HarnessSpec) -> list[Finding]:
    if spec.observability.capture_content:
        return [
            Finding(
                "warn",
                "content",
                "observability.capture_content is on: post-redaction content goes into spans (R9)",
            )
        ]
    return [Finding("ok", "content", "no prompt or output content in telemetry (R9)")]


def diagnose(path: Path, env: str | None, profile_dirs: list[Path]) -> list[Finding]:
    """Everything ``doctor`` reports. The spec's directory becomes importable, as for the app."""
    path = spec_path(path)
    findings = [
        Finding("warn", "plugins", problem) for problem in PluginCatalog.default().problems()
    ]
    try:
        harness = Harness.load(path, env=env, profile_dirs=profile_dirs)
    except HarnessError as exc:
        return [*findings, Finding("fail", "load", exc.message)]
    spec = harness.spec.spec
    findings += _level(harness)
    for task in harness.tasks:
        runner = harness.runner_of(task)
        findings.append(
            Finding("ok", "hooks", f"task {task}: runner {runner.name} reaches every hook it needs")
        )
    findings += _owners(harness) + _pins(spec) + _shadow(spec) + _content(spec)
    return findings


def doctor(
    path: Annotated[
        Path | None, typer.Argument(help="The app spec (default: harness.yaml).")
    ] = None,
    env: Annotated[
        str | None, typer.Option("--env", "-e", help="Overlay: harness.<env>.yaml.")
    ] = None,
    profile_dir: Annotated[list[Path] | None, typer.Option("--profile-dir")] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Exit 1 on warnings too.")] = False,
    output: Annotated[Literal["text", "json"], typer.Option("--format")] = "text",
) -> None:
    """Check a spec: adoption level, hooks, retry owners, pins, shadow guards, content."""
    findings = diagnose(spec_path(path), env, profile_dir or [])
    if output == "json":
        typer.echo(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        width = max(len(f.check) for f in findings)
        for finding in findings:
            typer.echo(
                f"{finding.severity.upper():<4}  {finding.check:<{width}}  {finding.message}"
            )
    worst = {f.severity for f in findings}
    if "fail" in worst or (strict and "warn" in worst):
        raise typer.Exit(code=1)
