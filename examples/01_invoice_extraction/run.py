"""Extract one invoice with the Run style (L1).

    HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/run.py

There is no retry loop, no try/except around the model and no tracing setup:
the harness owns all of that, as harness.yaml says.
"""

import asyncio
from pathlib import Path

from invoices.models import Invoice, InvoiceDoc
from invoices.samples import INVOICE_TEXT

import harnessweaver as hw

SPEC = Path(__file__).resolve().parent / "harness.yaml"


async def main() -> hw.RunResult:
    harness = hw.load(SPEC)
    result = await harness.run(
        "extract_invoice", InvoiceDoc(text=INVOICE_TEXT), principal="ap-clerk", tenant="acme"
    )
    print(f"status: {result.status.value}")
    if result.ok:
        invoice = Invoice.model_validate(result.output)
        print(f"invoice: {invoice.invoice_number} from {invoice.vendor}")
        print(f"total: {invoice.total:.2f} {invoice.currency} over {len(invoice.line_items)} lines")
    print(f"cost: ${result.cost_usd or 0:.6f}")
    return result


if __name__ == "__main__":
    asyncio.run(main())
