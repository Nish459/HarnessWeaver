"""What the support task returns."""

from pydantic import BaseModel, Field


class Reply(BaseModel):
    """An answer to one customer question."""

    intent: str = Field(description="The kind of question: outage, billing or howto.")
    answer: str
    sources: list[str] = Field(description="Ids of the articles the answer could cite.")
