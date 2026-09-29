"""Context errors expose bounded, public diagnostics without source payloads."""

from __future__ import annotations

from typing import Any

from c1.query.plan import QueryPlanError


class ContextError(QueryPlanError):
    def __init__(
        self, status: int, code: str, reason: str, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(status, code, reason)
        self.details = details or {}
