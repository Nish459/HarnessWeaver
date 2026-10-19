"""Building contributions from their config or ``sample`` settings (RULES C11)."""

from typing import Any

from harnessweaver.core.middleware import MiddlewareDef
from harnessweaver.core.plugins import (
    AdapterInfo,
    Contribution,
    ProviderInfo,
    RunnerInfo,
)
from harnessweaver.testing.conformance.common import Subject, expect

__all__ = ["build", "check_builds", "sample_settings"]


def sample_settings(sample: Any) -> dict[str, Any]:
    return dict(sample) if sample is not None else {}


def build(contribution: Contribution) -> Any:
    """A ready instance of a contribution, from its ``sample`` settings or defaults."""
    item = contribution.item
    if isinstance(item, ProviderInfo):
        return item.build(sample_settings(item.sample))
    if isinstance(item, MiddlewareDef):
        return item.build(sample_settings(item.sample) if item.is_class else None)
    if isinstance(item, RunnerInfo):
        return item.build(sample_settings(item.sample))
    return item.target()


def check_builds(subject: Subject) -> None:
    """Builds from its config model alone, or from its declared ``sample`` (C11)."""
    try:
        built = build(subject.contribution)
    except Exception as exc:
        where = "its sample" if getattr(subject.item, "sample", None) else "defaults"
        raise AssertionError(
            f"{subject.name} doesn't build from {where} ({type(exc).__name__}: {exc}); "
            "declare sample= settings"
        ) from exc
    expect(built is not None, f"{subject.name} built to None")
    if isinstance(subject.item, AdapterInfo):
        expect(callable(getattr(built, "bind", None)), f"adapter {subject.name} has no bind()")
