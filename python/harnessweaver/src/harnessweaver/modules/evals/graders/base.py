"""What every built-in grader's config shares: settings by ``SHORTHAND``."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

__all__ = ["GraderConfig", "nonempty", "texts"]


class GraderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    SHORTHAND: ClassVar[str | None] = None
    """The field a single setting fills; ``None`` when no single setting is accepted."""


def texts(value: str | tuple[str, ...]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else value


def nonempty(value: str | tuple[str, ...]) -> str | tuple[str, ...]:
    if not texts(value) or not all(texts(value)):
        raise ValueError("give at least one non-empty text")
    return value
