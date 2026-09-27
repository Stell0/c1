"""Transport-independent canonical RDF node records."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from c1.model.diagnostics import Diagnostic
from c1.model.literals import LiteralValue


class NodeRecord(BaseModel):
    """One addressable RDF subject; property strings are object IRIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    types: list[str] = Field(min_length=1)
    properties: dict[str, list[str | LiteralValue]]


class ValidatedBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    records: list[NodeRecord]
    diagnostics: list[Diagnostic] = Field(default_factory=list)
