"""Versioned, exact keyword normalization and matching."""

import re
import unicodedata
from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

from c1.model.diagnostics import Diagnostic
from c1.model.literals import normalize_language

NORMALIZATION_VERSION = "c1-kw-1"
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    first = unicodedata.normalize("NFKC", text)
    folded = first.casefold()
    second = unicodedata.normalize("NFKC", folded)
    return _WHITESPACE.sub(" ", second.strip())


class Keyword(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    language: str | None = None
    normalized: str | None = None
    normalization_version: str = NORMALIZATION_VERSION

    @model_validator(mode="after")
    def derive(self) -> Self:
        if not self.text or not self.text.strip():
            raise PydanticCustomError("C1-IX-021", "Keyword text must not be blank")
        if self.normalization_version != NORMALIZATION_VERSION:
            raise PydanticCustomError("C1-IX-021", "Unsupported keyword normalization version")
        expected = normalize(self.text)
        if self.normalized is not None and self.normalized != expected:
            raise PydanticCustomError("C1-IX-021", "Keyword normalized form does not match text")
        object.__setattr__(self, "normalized", expected)
        if self.language is not None:
            object.__setattr__(self, "language", normalize_language(self.language))
        return self


def coalesce(keywords: Iterable[Keyword]) -> tuple[list[Keyword], list[Diagnostic]]:
    first: list[Keyword] = []
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str | None, str]] = set()
    for index, keyword in enumerate(keywords):
        assert keyword.normalized is not None
        key = (keyword.language, keyword.normalized)
        if key in seen:
            diagnostics.append(
                Diagnostic(
                    code="C1-KW-001",
                    severity="info",
                    path=f"/{index}",
                    message="Duplicate keyword dropped; first spelling retained",
                )
            )
            continue
        first.append(keyword)
        seen.add(key)
    return first, diagnostics


def _matches(entity: Keyword, query: Keyword) -> bool:
    return entity.normalized == query.normalized and (
        query.language is None or entity.language == query.language
    )


def match_any(entity_keywords: Iterable[Keyword], query: Iterable[Keyword]) -> bool:
    entities = tuple(entity_keywords)
    queries = tuple(query)
    return not queries or any(_matches(entity, item) for item in queries for entity in entities)


def match_all(entity_keywords: Iterable[Keyword], query: Iterable[Keyword]) -> bool:
    entities = tuple(entity_keywords)
    return all(any(_matches(entity, item) for entity in entities) for item in query)
