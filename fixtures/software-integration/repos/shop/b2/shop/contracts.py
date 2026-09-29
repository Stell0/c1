"""Declared links from client functions to ledger API operations."""

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable[..., object])


def calls_operation(operation_id: str) -> Callable[[F], F]:
    def mark(function: F) -> F:
        function.__dict__["ledger_operation"] = operation_id
        return function

    return mark
