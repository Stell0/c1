import os

from shop.client import submit_order


def test_submit_order_against_live_ledger() -> None:
    result = submit_order(os.environ["LEDGER_URL"], "acme", {"quantity": 2, "unit_price": 5})
    assert result["amount"] == 10
