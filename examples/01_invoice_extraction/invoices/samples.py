"""A made-up invoice (S7: every name, address and number here is fake)."""

INVOICE_TEXT = """\
INVOICE INV-2026-0042
Northwind Supplies Ltd, 1 Example Street, Springfield
Billed to: Acme Corp, accounts@example.com
Issued: 2026-09-30    Due: 2026-10-30

3 x Ergonomic chair  @ 250.00   750.00
2 x Standing desk    @ 400.00   800.00

Subtotal 1550.00   VAT 20% 310.00   Total EUR 1860.00
Questions? Call 555-123-4567
"""

# The invoice above, as Invoice expects it.
EXPECTED = {
    "invoice_number": "INV-2026-0042",
    "vendor": "Northwind Supplies Ltd",
    "issued_on": "2026-09-30",
    "due_on": "2026-10-30",
    "currency": "EUR",
    "line_items": [
        {"description": "Ergonomic chair", "quantity": 3, "unit_price": 250.0, "amount": 750.0},
        {"description": "Standing desk", "quantity": 2, "unit_price": 400.0, "amount": 800.0},
    ],
    "subtotal": 1550.0,
    "tax": 310.0,
    "total": 1860.0,
}
