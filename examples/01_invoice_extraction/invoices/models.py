"""What goes into the extract_invoice task and what comes out.

Amounts are floats to keep the example short; a real ledger would use integer
cents or ``Decimal``.
"""

from datetime import date

from pydantic import BaseModel, Field


class InvoiceDoc(BaseModel):
    """The text of one invoice, as a PDF parser or OCR produced it."""

    text: str


class LineItem(BaseModel):
    description: str
    quantity: float = Field(gt=0)
    unit_price: float
    amount: float


class Invoice(BaseModel):
    """The typed invoice the model must return."""

    invoice_number: str
    vendor: str
    issued_on: date
    due_on: date | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code, such as EUR.")
    line_items: list[LineItem] = Field(min_length=1)
    subtotal: float
    tax: float = 0.0
    total: float
