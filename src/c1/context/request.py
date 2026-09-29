"""Strict, read-only context request grammar."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from c1.model.diagnostics import ProfileError
from c1.model.ids import validate_iri
from c1.model.keywords import Keyword, normalize
from c1.query.filters import KeywordTerm, _revision

ContextFormat = Literal["markdown", "structured"]
DEFAULT_FORMATS: list[ContextFormat] = ["markdown", "structured"]


class IDSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str

    @field_validator("id")
    @classmethod
    def check_id(cls, value: str) -> str:
        return validate_iri(value)


class LabelSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    label: str = Field(min_length=1, max_length=4096)
    language: str | None = None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: str) -> str:
        if not normalize(value):
            raise ValueError("label must not be blank")
        return value

    @field_validator("language")
    @classmethod
    def check_language(cls, value: str | None) -> str | None:
        return Keyword(text="language", language=value).language


class ContextBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    unit: Literal["bytes"] = "bytes"
    maximum: int = Field(default=65536, ge=2048, le=524288)


class ContextRequest(BaseModel):
    """Explicit selectors and narrowing; profile fields are checked by the service."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    profile: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    profile_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$", max_length=32)
    anchor: IDSelector | LabelSelector
    topics: list[str | IDSelector | LabelSelector] = Field(default_factory=list, max_length=200)
    keywords_all: list[KeywordTerm] = Field(default_factory=list, max_length=200)
    keywords_any: list[KeywordTerm] = Field(default_factory=list, max_length=200)
    fields: list[str] = Field(default_factory=list, max_length=200)
    project_ref: str | None = None
    revision: str | None = None
    formats: list[ContextFormat] = Field(
        default_factory=lambda: list(DEFAULT_FORMATS), min_length=1, max_length=2
    )
    budget: ContextBudget = Field(default_factory=ContextBudget)
    cursor: str | None = Field(default=None, min_length=1, max_length=16384)

    @field_validator("topics", mode="before")
    @classmethod
    def canonicalize_topic_iris(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        result: list[object] = []
        for item in value:
            if isinstance(item, str):
                try:
                    validate_iri(item)
                except ProfileError:
                    pass
                else:
                    item = IDSelector(id=item)
            result.append(item)
        return result

    @field_validator("topics")
    @classmethod
    def check_topics(
        cls, values: list[str | IDSelector | LabelSelector]
    ) -> list[str | IDSelector | LabelSelector]:
        if any(
            isinstance(value, str) and (not normalize(value) or len(value) > 4096)
            for value in values
        ):
            raise ValueError("topic must be a nonblank label or an explicit selector")
        return values

    @field_validator("project_ref")
    @classmethod
    def check_project_ref(cls, value: str | None) -> str | None:
        return validate_iri(value) if value is not None else None

    @field_validator("revision")
    @classmethod
    def check_revision(cls, value: str | None) -> str | None:
        return _revision(value)

    @model_validator(mode="after")
    def check_lists(self) -> Self:
        if len(self.formats) != len(set(self.formats)):
            raise ValueError("formats must be unique")
        if any(not field or len(field) > 128 for field in self.fields):
            raise ValueError("invalid field name")
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("fields must be unique")
        return self


def request_digest(request: ContextRequest) -> str:
    """Bind continuations to selection and rendering; budget may change per page."""
    value = request.model_dump(mode="json", exclude={"cursor", "budget", "revision"})
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
