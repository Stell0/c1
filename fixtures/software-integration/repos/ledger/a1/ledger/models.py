"""Invoice data model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    customer: str
    amount: int
