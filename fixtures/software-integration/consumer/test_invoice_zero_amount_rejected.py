"""Reviewed consumer test written from the C1 test-development package (M09 D10).

Goal: conformance for `ledger.api.create_invoice` at target {a1, b1}. The
oracle is the normative evidence only, never the a1 implementation:

C1-evidence: urn:c1:instance:dev:part/745b6703-5f4f-4979-8a11-7b92f4a1d078
C1-evidence: urn:c1:instance:dev:part/83af3ebf-c29a-411b-a745-cd2bb2cc44df

The first is `docs/invoicing.md` ("The amount must be greater than zero; zero
is rejected with 422."); the second is the 1.0.0 `openapi.json` contract. This
file is fixture data run by the external consumer, never by C1.
"""

import pytest

from ledger.api import InvalidAmount, create_invoice


def test_zero_amount_is_rejected() -> None:
    with pytest.raises(InvalidAmount):
        create_invoice("acme", 0)
