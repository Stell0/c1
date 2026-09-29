"""Minimal HTTP transport to the ledger API."""

import json
from urllib import request


def post_invoice(base_url: str, customer: str, amount: int) -> dict[str, object]:
    body = json.dumps({"customer": customer, "amount": amount}).encode()
    req = request.Request(base_url + "/invoices", data=body, method="POST")
    with request.urlopen(req) as response:
        return json.loads(response.read())
