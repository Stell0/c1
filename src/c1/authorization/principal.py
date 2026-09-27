"""Stable issuer-and-subject principal identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_ALIAS = re.compile(r"^[a-z][a-z0-9_-]*$")
_SUBJECT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class Principal:
    issuer_alias: str
    subject: str
    kind: Literal["human", "service"]

    def __post_init__(self) -> None:
        if not _ALIAS.fullmatch(self.issuer_alias):
            raise ValueError("Invalid trusted issuer alias")
        if not _SUBJECT.fullmatch(self.subject):
            raise ValueError("Unsupported subject identifier")
        if self.kind not in {"human", "service"}:
            raise ValueError("Unsupported principal kind")

    @property
    def id(self) -> str:
        # Alias contains no dot, so the first dot is an unambiguous boundary.
        return f"user:{self.issuer_alias}.{self.subject}"
