"""Restricted pricing rules; bound to a restricted scope in the fixture."""


def price(order: dict[str, int]) -> int:
    return order["quantity"] * order["unit_price"]
