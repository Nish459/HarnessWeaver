"""The help desk's typed outputs."""

from typing import Literal

from pydantic import BaseModel


class Ticket(BaseModel):
    """A triaged support ticket."""

    summary: str
    priority: Literal["low", "high"]
