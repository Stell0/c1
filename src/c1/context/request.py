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


class TargetSelector(BaseModel):
    """An explicit software target set; branch names resolve only through the software API."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    target_set_id: str | None = None
    snapshots: list[str] = Field(default_factory=list, max_length=50)
    contracts: list[str] = Field(default_factory=list, max_length=50)
    configurations: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("target_set_id")
    @classmethod
    def check_target_set(cls, value: str | None) -> str | None:
        return validate_iri(value) if value is not None else None

    @field_validator("snapshots", "contracts", "configurations")
    @classmethod
    def check_members(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("target members must be unique")
        return [validate_iri(value) for value in values]

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        members = self.snapshots or self.contracts or self.configurations
        if self.target_set_id is not None and members:
            raise ValueError("target_set_id excludes inline members")
        if self.target_set_id is None and not self.snapshots:
            raise ValueError("a target needs snapshots or a target_set_id")
        return self

    def spec(self) -> dict[str, object]:
        if self.target_set_id is not None:
            return {"target_set_id": self.target_set_id}
        return {
            "snapshots": list(self.snapshots),
            "contracts": list(self.contracts),
            "configurations": list(self.configurations),
        }


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
    # Software-task profiles only (M09 D1); graph profiles reject both.
    target: TargetSelector | None = None
    goal: Literal["conformance", "characterization"] | None = None

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
    value = request.model_dump(
        mode="json", exclude={"cursor", "budget", "revision", "target", "goal"}
    )
    # Absent software fields leave graph-profile digests exactly as in M07.
    for key in ("target", "goal"):
        if getattr(request, key) is not None:
            value[key] = request.model_dump(mode="json", include={key})[key]
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
