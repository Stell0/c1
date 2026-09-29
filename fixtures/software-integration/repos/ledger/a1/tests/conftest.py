import pytest

from ledger.models import Invoice


@pytest.fixture
def sample_invoice() -> Invoice:
    return Invoice(invoice_id="inv-acme-10", customer="acme", amount=10)
