"""Adoption levels and the two kinds of spec block: strict, and provider-selecting."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = ["API_VERSION", "Level", "ProviderModel", "StrictModel"]

API_VERSION = "harnessweaver/v1"


class Level(StrEnum):
    """Adoption levels (DESIGNS No. 11)."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"

    @property
    def rank(self) -> int:
        return int(self.value[1])


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ProviderModel(BaseModel):
    """A block that selects a provider. Extra keys are that provider's settings."""

    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)

    def provider_settings(self) -> dict[str, Any]:
        """The keys that belong to the provider rather than to HarnessWeaver."""
        return dict(self.model_extra or {})
