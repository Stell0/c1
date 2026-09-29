"""HTTP handlers for the ledger API (see openapi.json)."""

from ledger import store
from ledger.models import Invoice


class InvalidAmount(ValueError):
    pass


def validate(amount: int) -> bool:
    return amount >= 0


def create_invoice(customer: str, amount: int) -> Invoice:
    if not validate(amount):
        raise InvalidAmount(amount)
    invoice = Invoice(invoice_id=f"inv-{customer}-{amount}", customer=customer, amount=amount)
    store.save(invoice)
    return invoice


def get_invoice(invoice_id: str) -> Invoice | None:
    return store.load(invoice_id)
