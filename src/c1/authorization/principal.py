"""Stable issuer-and-subject principal identity."""

from __future__ import annotations

import base64
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
        if (
            not isinstance(self.subject, str)
            or not self.subject
            or (len(self.subject) > 255 and not _SUBJECT.fullmatch(self.subject))
            or any(ord(char) < 32 or ord(char) > 126 for char in self.subject)
        ):
            raise ValueError("Unsupported subject identifier")
        if self.kind not in {"human", "service"}:
            raise ValueError("Unsupported principal kind")

    @property
    def id(self) -> str:
        # Alias contains no dot, so the first dot is an unambiguous boundary.
        return f"user:{self.issuer_alias}.{self.subject_component}"

    @property
    def subject_component(self) -> str:
        subject = self.subject
        if not _SUBJECT.fullmatch(subject):
            # '~' cannot occur in a legacy ID. Base64url is injective over the
            # exact ASCII bytes; no case folding, normalization or truncation.
            subject = "~" + base64.urlsafe_b64encode(subject.encode("ascii")).rstrip(b"=").decode()
        return subject

    @classmethod
    def from_id(cls, identifier: str, kind: Literal["human", "service"] = "human") -> Principal:
        """Decode only canonical stored IDs, retaining legacy representation."""
        if not identifier.startswith("user:") or "." not in identifier[5:]:
            raise ValueError("Invalid principal identifier")
        alias, subject = identifier[5:].split(".", 1)
        if subject.startswith("~"):
            text = subject[1:]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
                raise ValueError("Invalid encoded principal identifier")
            try:
                subject = base64.b64decode(
                    text + "=" * (-len(text) % 4), altchars=b"-_", validate=True
                ).decode("ascii")
            except (ValueError, UnicodeError):
                raise ValueError("Invalid encoded principal identifier") from None
        result = cls(alias, subject, kind)
        if result.id != identifier:
            raise ValueError("Noncanonical principal identifier")
        return result
