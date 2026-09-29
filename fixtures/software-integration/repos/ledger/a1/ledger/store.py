"""In-memory invoice storage."""

from ledger.models import Invoice

_INVOICES: dict[str, Invoice] = {}


def save(invoice: Invoice) -> None:
    _INVOICES[invoice.invoice_id] = invoice


def load(invoice_id: str) -> Invoice | None:
    return _INVOICES.get(invoice_id)
