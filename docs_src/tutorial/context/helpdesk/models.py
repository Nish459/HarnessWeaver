"""What goes into the support desk's tasks and what comes out."""

from typing import Literal

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """A message a customer sent to the support desk."""

    text: str


class Triage(BaseModel):
    """How the desk should handle a ticket."""

    category: Literal["billing", "bug", "account", "other"]
    priority: int = Field(ge=1, le=4, description="1 is the most urgent.")
    summary: str = Field(description="One sentence: what the customer wants.")
