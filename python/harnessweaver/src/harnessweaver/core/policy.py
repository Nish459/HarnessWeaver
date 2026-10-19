"""Policy: what a ``PolicyEngine`` is asked, and how its rules combine (DESIGNS No. 17, R3).

Every engine reads the same rules (``policy.rules``) and combines them the same
way (ADR-0025, fixtures suite ``governor``):

* A rule applies at one hook: ``tool.before`` (the default) or ``run.start``.
* Of the rules whose ``when`` is true, the most restrictive effect wins:
  ``deny`` over ``require_approval`` over ``allow``. Among equally restrictive
  rules, the first one decides.
* A ``when`` that can't be evaluated never loosens a decision: a ``deny`` or
  ``require_approval`` rule then counts as matching, an ``allow`` rule doesn't.
* When no rule matches, ``default_effect`` decides a tool call. A run is only
  restricted by its own rules, so ``run.start`` defaults to ``allow``.
"""

from collections.abc import Callable, Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.decisions import PolicyEffect
from harnessweaver.core.envelope import Labels, Principal
from harnessweaver.core.tools import ToolInfo

__all__ = [
    "RUN_POLICY_VARIABLES",
    "TOOL_POLICY_VARIABLES",
    "PolicyConfig",
    "PolicyDecision",
    "PolicyHook",
    "PolicyRequest",
    "PolicyRule",
    "decide_by_rules",
]

type PolicyHook = Literal["tool.before", "run.start"]

TOOL_POLICY_VARIABLES: Final = frozenset({"principal", "tenant", "task", "tool", "args", "labels"})
"""Names a ``tool.before`` rule may use."""

RUN_POLICY_VARIABLES: Final = frozenset({"principal", "tenant", "task", "labels"})
"""Names a ``run.start`` rule may use."""


class PolicyRule(BaseModel):
    """One ``policy.rules`` entry. ``when`` is true when the rule applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str | None = None
    when: str = Field(description="Predicate over principal, tenant, task, tool, args, labels.")
    effect: PolicyEffect
    reason: str | None = None
    hook: Literal["tool.before", "run.start"] = Field(
        default="tool.before", description="Where the rule applies."
    )


class PolicyConfig(BaseModel):
    """What every ``PolicyEngine`` is built from: the spec's rules and default effect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[PolicyRule, ...] = ()
    default_effect: PolicyEffect = PolicyEffect.ALLOW


class PolicyRequest(BaseModel):
    """The question a ``PolicyEngine`` answers: may this run, or this call, go ahead?"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook: Literal["tool.before", "run.start"] = "tool.before"
    principal: Principal
    tenant: str
    task: str | None = None
    task_version: str | None = None
    tool: ToolInfo | None = Field(default=None, description="The tool, for tool.before.")
    args: dict[str, JsonValue] | None = Field(default=None, description="The call's arguments.")
    labels: Labels = Labels()

    def variables(self) -> dict[str, JsonValue]:
        """The names a rule's ``when`` sees, as plain JSON values."""
        variables: dict[str, JsonValue] = {
            "principal": self.principal.model_dump(mode="json"),
            "tenant": self.tenant,
            "task": {"name": self.task, "version": self.task_version},
            "labels": self.labels.model_dump(mode="json"),
        }
        if self.hook == "tool.before":
            variables["tool"] = self.tool.model_dump(mode="json") if self.tool else None
            variables["args"] = dict(self.args or {})
        return variables


class PolicyDecision(BaseModel):
    """A ``PolicyEngine``'s answer, with the rule that decided it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effect: PolicyEffect
    rule: str | None = Field(default=None, description="The deciding rule's id; None if default.")
    reason: str | None = None


def decide_by_rules(
    rules: Sequence[PolicyRule],
    default_effect: PolicyEffect,
    hook: PolicyHook,
    matches: Callable[[PolicyRule], bool | None],
) -> PolicyDecision:
    """Combine ``rules`` as every engine must (see the module docs).

    Args:
        rules: The rules, in spec order.
        default_effect: The effect when no ``tool.before`` rule matches.
        hook: Which rules apply.
        matches: Evaluates one rule's ``when``: ``True``, ``False``, or ``None``
            when it can't be evaluated.
    """
    best: PolicyDecision | None = None
    for index, rule in enumerate(rules):
        if rule.hook != hook:
            continue
        label = rule.id or f"rule#{index + 1}"
        matched = matches(rule)
        if matched is None:
            if rule.effect is PolicyEffect.ALLOW:
                continue
            reason = f"policy rule {label} couldn't be checked"
        elif not matched:
            continue
        else:
            reason = rule.reason or f"policy rule {label}"
        if best is None or rule.effect.rank > best.effect.rank:
            best = PolicyDecision(effect=rule.effect, rule=label, reason=reason)
    if best is not None:
        return best
    effect = default_effect if hook == "tool.before" else PolicyEffect.ALLOW
    return PolicyDecision(effect=effect, reason=f"no policy rule matched; default {effect.value}")
