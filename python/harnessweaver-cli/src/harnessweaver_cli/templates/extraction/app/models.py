"""What goes into the extraction task and what comes out."""

from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A customer support message."""

    text: str


class TicketSummary(BaseModel):
    """The structured summary the model must return."""

    category: Literal["billing", "bug", "account", "other"]
    priority: int = Field(ge=1, le=4, description="1 is the most urgent.")
    product: str
    summary: str
