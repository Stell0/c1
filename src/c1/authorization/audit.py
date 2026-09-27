"""An allowlisted audit event format; callers cannot attach request content."""

from __future__ import annotations

import json
import logging
import sys
from uuid import uuid4

_LOGGER = logging.getLogger("c1.audit")


class Audit:
    def __init__(self) -> None:
        _LOGGER.setLevel(logging.INFO)
        if not _LOGGER.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            _LOGGER.addHandler(handler)

    def emit(
        self,
        principal: str,
        operation: str,
        target: str = "",
        outcome: str = "denied",
        reason: str = "",
        correlation_id: str = "",
    ) -> None:
        event = {
            "correlation_id": correlation_id or str(uuid4()),
            "principal": principal,
            "operation": operation,
            "target": target,
            "outcome": outcome,
            "reason": reason,
        }
        _LOGGER.info(json.dumps(event, sort_keys=True))
