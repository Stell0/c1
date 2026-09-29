from ledger.api import create_invoice, get_invoice


def test_create_invoice_stores_invoice() -> None:
    invoice = create_invoice("acme", 10)
    assert get_invoice(invoice.invoice_id) == invoice
