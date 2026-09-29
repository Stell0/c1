from unittest import mock

from shop.client import submit_order


def test_submit_order_with_mocked_ledger() -> None:
    with mock.patch("shop.ledger_client.post_invoice", return_value={"invoice_id": "x"}):
        assert submit_order("http://ledger", "acme", {"quantity": 1, "unit_price": 5})
