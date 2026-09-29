"""Order submission that creates ledger invoices."""

from shop import ledger_client, pricing_internal
from shop.contracts import calls_operation


def validate(order: dict[str, int]) -> bool:
    return order.get("quantity", 0) > 0


@calls_operation("createInvoice")
def submit_order(base_url: str, customer: str, order: dict[str, int]) -> dict[str, object]:
    if not validate(order):
        raise ValueError("empty order")
    amount = pricing_internal.price(order)
    return ledger_client.post_invoice(base_url, customer, amount)
