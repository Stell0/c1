"""Pure M05 filter grammar and evaluation over an already authorized selection.

Callers must pass only records whose *current* bindings have been checked. In
particular, assertions and keyword nodes are independent resources; this
module never fetches them or treats references as authorization grants.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from c1.model.ids import validate_iri
from c1.model.keywords import Keyword, match_all, match_any, normalize
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, RDF, SKOS
from c1.model.time import TEMPORAL_TYPES, XSD, TimeInterval, temporal_bounds

_NUMERIC = {XSD + "integer", XSD + "decimal", XSD + "double"}
_STRING = {XSD_STRING, RDF + "langString", XSD + "anyURI"}
_COMPARISON = {"eq", "ne", "lt", "le", "gt", "ge"}
_SCOPE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_REVISION = re.compile(r"(?:branch:|commit:)?[A-Za-z0-9_-]{1,128}\Z")


def _revision(value: str | None) -> str | None:
    if value is not None and _REVISION.fullmatch(value) is None:
        raise ValueError("invalid revision")
    return value


class LabelFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(min_length=1)
    mode: Literal["exact", "prefix"] = "exact"
    language: str | None = None

    @field_validator("language")
    @classmethod
    def check_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return Keyword(text="language", language=value).language


class KeywordTerm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(min_length=1)
    language: str | None = None

    @model_validator(mode="after")
    def check_term(self) -> Self:
        keyword = Keyword(text=self.text, language=self.language)
        object.__setattr__(self, "language", keyword.language)
        return self

    def keyword(self) -> Keyword:
        return Keyword(text=self.text, language=self.language)


class PropertyFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    predicate: str = Field(min_length=1)
    op: Literal["eq", "ne", "lt", "le", "gt", "ge", "exists"]
    value: LiteralValue | str | None = None

    @field_validator("predicate")
    @classmethod
    def check_predicate(cls, value: str) -> str:
        return validate_iri(value)

    @model_validator(mode="after")
    def check_value(self) -> Self:
        if self.op == "exists" and self.value is not None:
            raise ValueError("exists does not take a value")
        if self.op != "exists" and self.value is None:
            raise ValueError("comparison requires a value")
        if isinstance(self.value, str) and self.op not in {"eq", "ne", "exists"}:
            raise ValueError("IRI supports only eq and ne")
        if isinstance(self.value, str):
            validate_iri(self.value)
        return self


class RelationFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    predicate: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    direction: Literal["out", "in"] = "out"

    @field_validator("predicate", "target_id")
    @classmethod
    def check_iri(cls, value: str) -> str:
        return validate_iri(value)


class QueryFilters(BaseModel):
    """Strict combined entity search grammar. Cursor is excluded from digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    types: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list, max_length=200)
    label: LabelFilter | None = None
    alias: LabelFilter | None = None
    keywords_any: list[KeywordTerm] = Field(default_factory=list)
    keywords_all: list[KeywordTerm] = Field(default_factory=list)
    properties: list[PropertyFilter] = Field(default_factory=list)
    relations: list[RelationFilter] = Field(default_factory=list)
    review_state: list[Literal["reported", "confirmed", "disputed"]] = Field(default_factory=list)
    lifecycle: list[Literal["active", "superseded", "retracted"]] = Field(default_factory=list)
    scope_ids: list[str] = Field(default_factory=list)
    project_ref: str | None = None
    valid_at: str | None = None
    include_unknown: StrictBool = False
    revision: str | None = None
    order: Literal["id", "label", "recorded"] = "id"
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None

    @field_validator("types", "ids")
    @classmethod
    def check_iris(cls, values: list[str]) -> list[str]:
        return [validate_iri(value) for value in values]

    @field_validator("scope_ids")
    @classmethod
    def check_scope_ids(cls, values: list[str]) -> list[str]:
        if any(_SCOPE_ID.fullmatch(value) is None for value in values):
            raise ValueError("invalid scope identifier")
        return values

    @field_validator("revision")
    @classmethod
    def check_revision(cls, value: str | None) -> str | None:
        return _revision(value)

    @field_validator("project_ref")
    @classmethod
    def check_project_ref(cls, value: str | None) -> str | None:
        return validate_iri(value) if value is not None else None

    @field_validator("valid_at")
    @classmethod
    def check_valid_at(cls, value: str | None) -> str | None:
        if value is not None:
            temporal_bounds(value, XSD + "dateTimeStamp")
        return value


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: Literal["match", "no_match", "indeterminate"]
    matched_filters: tuple[str, ...] = ()
    rule: str | None = None

    @property
    def included(self) -> bool:
        return self.status == "match" or self.status == "indeterminate"


def filter_digest(filters: QueryFilters) -> str:
    """Bind cursor to search semantics, excluding pagination position/size."""
    # Revision is independently bound by the cursor, including when the
    # first page implicitly selected the repository head.
    value = filters.model_dump(mode="json", exclude={"cursor", "limit", "revision"})
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AssertionFilters(BaseModel):
    """Strict filters for the assertion list route."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    subject: str | None = None
    predicate: str | None = None
    object: LiteralValue | str | None = None
    review_state: list[Literal["reported", "confirmed", "disputed"]] = Field(default_factory=list)
    lifecycle: list[Literal["active", "superseded", "retracted"]] = Field(default_factory=list)
    valid_at: str | None = None
    include_unknown: StrictBool = False
    revision: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None

    @field_validator("subject", "predicate")
    @classmethod
    def check_iri(cls, value: str | None) -> str | None:
        return validate_iri(value) if value is not None else None

    @field_validator("valid_at")
    @classmethod
    def check_valid_at(cls, value: str | None) -> str | None:
        return QueryFilters.check_valid_at(value)

    @field_validator("revision")
    @classmethod
    def check_revision(cls, value: str | None) -> str | None:
        return _revision(value)

    @model_validator(mode="after")
    def check_object(self) -> Self:
        if isinstance(self.object, str):
            validate_iri(self.object)
        return self


def _values(node: NodeRecord, predicate: str) -> list[str | LiteralValue]:
    return node.properties.get(predicate, [])


def _text(node: NodeRecord, predicate: str) -> str | None:
    return next(
        (value.lexical for value in _values(node, predicate) if isinstance(value, LiteralValue)),
        None,
    )


def _labels_match(values: list[str | LiteralValue], query: LabelFilter) -> bool:
    needle = normalize(query.text) if query.mode == "exact" else _prefix_text(query.text)
    return any(
        isinstance(value, LiteralValue)
        and (query.language is None or value.language == query.language)
        and (
            normalize(value.lexical) == needle
            if query.mode == "exact"
            else _prefix_text(value.lexical).startswith(needle)
        )
        for value in values
    )


def _prefix_text(value: str) -> str:
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value).casefold())


def _keyword(node: NodeRecord) -> Keyword | None:
    text = _text(node, C1 + "keywordText")
    if text is None:
        return None
    return Keyword(text=text, language=_text(node, C1 + "keywordLanguage"))


def _temporal_key(value: str) -> tuple[int, int, int, int, int, Decimal]:
    # temporal_bounds returns UTC in a stable form, including BCE and years >9999.
    date, clock = value.removesuffix("Z").split("T")
    year, month, day = date.rsplit("-", 2)
    hour, minute, second = clock.split(":")
    return int(year), int(month), int(day), int(hour), int(minute), Decimal(second)


def _scalar(literal: LiteralValue) -> Any:
    value = " ".join(literal.lexical.split())
    kind = literal.datatype
    if kind in _NUMERIC:
        if value == "NaN":
            return None
        if value in {"INF", "+INF"}:
            return math.inf
        if value == "-INF":
            return -math.inf
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    if kind == XSD + "boolean":
        return value in {"true", "1"}
    if kind in _STRING:
        return literal.lexical
    if kind.startswith(XSD) and kind.removeprefix(XSD) in {
        "dateTime",
        "dateTimeStamp",
        "date",
        "gYearMonth",
        "gYear",
    }:
        start, end, timezone_unknown = temporal_bounds(value, kind)
        if timezone_unknown or start != end:
            return None
        return _temporal_key(start)
    return None


def _compare(actual: str | LiteralValue, query: PropertyFilter) -> bool:
    expected = query.value
    if query.op == "exists":
        return True
    if isinstance(actual, str) or isinstance(expected, str):
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        return (actual == expected) if query.op == "eq" else (actual != expected)
    if not isinstance(actual, LiteralValue) or not isinstance(expected, LiteralValue):
        return False
    if actual.datatype != expected.datatype and not (
        actual.datatype in _NUMERIC
        and expected.datatype in _NUMERIC
        or actual.datatype in TEMPORAL_TYPES
        and expected.datatype in TEMPORAL_TYPES
    ):
        return False
    if actual.language != expected.language:
        return False
    if actual.datatype in TEMPORAL_TYPES:
        if expected.datatype not in TEMPORAL_TYPES:
            return False
        a_start, a_end, a_unknown = temporal_bounds(actual.lexical.strip(), actual.datatype)
        b_start, b_end, b_unknown = temporal_bounds(expected.lexical.strip(), expected.datatype)
        if a_unknown or b_unknown:
            return False
        left_start, left_end = _temporal_key(a_start), _temporal_key(a_end)
        right_start, right_end = _temporal_key(b_start), _temporal_key(b_end)
        if query.op == "eq":
            return (left_start, left_end) == (right_start, right_end)
        if query.op == "ne":
            return left_end <= right_start or right_end <= left_start
        if query.op == "lt":
            return left_end < right_start or (left_end == right_start and left_start < right_start)
        if query.op == "le":
            return left_end <= right_start or (left_start, left_end) == (right_start, right_end)
        if query.op == "gt":
            return right_end < left_start or (right_end == left_start and right_start < left_start)
        if query.op == "ge":
            return right_end <= left_start or (left_start, left_end) == (right_start, right_end)
        return False
    left, right = _scalar(actual), _scalar(expected)
    if left is None or right is None:
        return False
    try:
        if query.op == "eq":
            return bool(left == right)
        if query.op == "ne":
            return bool(left != right)
        if query.op == "lt":
            return bool(left < right)
        if query.op == "le":
            return bool(left <= right)
        if query.op == "gt":
            return bool(left > right)
        if query.op == "ge":
            return bool(left >= right)
        return False
    except TypeError:
        return False


def _assertion_parts(
    assertion: NodeRecord,
) -> tuple[str | None, str | None, str | LiteralValue | None]:
    subject = next((v for v in _values(assertion, RDF + "subject") if isinstance(v, str)), None)
    predicate = next((v for v in _values(assertion, RDF + "predicate") if isinstance(v, str)), None)
    obj = next(iter(_values(assertion, RDF + "object")), None)
    return subject, predicate, obj


def _active(assertion: NodeRecord) -> bool:
    return _text(assertion, C1 + "lifecycle") in {None, "active"}


def valid_at_status(
    interval: TimeInterval | None, instant: str
) -> Literal["match", "no_match", "indeterminate"]:
    """World-valid point membership; unknown/coarse timezone never becomes a fact."""
    temporal_bounds(instant, XSD + "dateTimeStamp")
    if interval is None or interval.timezone_unknown:
        return "indeterminate"
    if interval.start.state == "unknown" or interval.end.state == "unknown":
        return "indeterminate"
    point = _temporal_key(temporal_bounds(instant, XSD + "dateTimeStamp")[0])
    if interval.start.state == "known":
        assert interval.start.earliest is not None
        if point < _temporal_key(interval.start.earliest):
            return "no_match"
    if interval.end.state == "known":
        assert interval.end.latest is not None
        if point >= _temporal_key(interval.end.latest):
            return "no_match"
    return "match"


def evaluate_entity(
    node: NodeRecord,
    filters: QueryFilters,
    *,
    keywords_by_id: dict[str, NodeRecord] | None = None,
    assertions: tuple[NodeRecord, ...] = (),
    readable_entity_ids: frozenset[str] = frozenset(),
    intervals_by_id: dict[str, TimeInterval] | None = None,
    scope_id: str | None = None,
    recorded_at: str | None = None,
) -> MatchResult:
    """Evaluate a candidate entity with no implicit joins or backend access.

    The caller supplies only fully authorized assertions. Relationship joins
    additionally require both endpoints in ``readable_entity_ids``.
    """
    matched: list[str] = []
    if filters.ids and node.id not in filters.ids:
        return MatchResult("no_match")
    if filters.types and not set(filters.types).intersection(node.types):
        return MatchResult("no_match")
    if filters.label and not _labels_match(_values(node, SKOS + "prefLabel"), filters.label):
        return MatchResult("no_match")
    if filters.alias and not _labels_match(_values(node, SKOS + "altLabel"), filters.alias):
        return MatchResult("no_match")
    if filters.scope_ids and scope_id not in filters.scope_ids:
        return MatchResult("no_match")
    if filters.project_ref and filters.project_ref not in _values(node, C1 + "projectReference"):
        return MatchResult("no_match")
    if filters.lifecycle and _text(node, C1 + "lifecycle") not in filters.lifecycle:
        return MatchResult("no_match")
    for field in ("ids", "types", "label", "alias", "scope_ids", "project_ref", "lifecycle"):
        if getattr(filters, field):
            matched.append(field)

    if filters.keywords_any or filters.keywords_all:
        authorized = keywords_by_id or {}
        keywords = [
            value
            for iri in _values(node, C1 + "keyword")
            if isinstance(iri, str) and iri in authorized
            if (value := _keyword(authorized[iri])) is not None
        ]
        if filters.keywords_any and not match_any(
            keywords, (q.keyword() for q in filters.keywords_any)
        ):
            return MatchResult("no_match")
        if filters.keywords_all and not match_all(
            keywords, (q.keyword() for q in filters.keywords_all)
        ):
            return MatchResult("no_match")
        matched.extend(
            field for field in ("keywords_any", "keywords_all") if getattr(filters, field)
        )

    relevant = tuple(a for a in assertions if _active(a))
    for property_query in filters.properties:
        if not any(
            subject == node.id
            and predicate == property_query.predicate
            and obj is not None
            and _compare(obj, property_query)
            for subject, predicate, obj in map(_assertion_parts, relevant)
        ):
            return MatchResult("no_match")
    if filters.properties:
        matched.append("properties")
    for relation_query in filters.relations:
        if (
            relation_query.target_id not in readable_entity_ids
            or node.id not in readable_entity_ids
        ):
            return MatchResult("no_match")
        if not any(
            predicate == relation_query.predicate
            and isinstance(obj, str)
            and subject in readable_entity_ids
            and obj in readable_entity_ids
            and (
                (subject == node.id and obj == relation_query.target_id)
                if relation_query.direction == "out"
                else (subject == relation_query.target_id and obj == node.id)
            )
            for subject, predicate, obj in map(_assertion_parts, relevant)
        ):
            return MatchResult("no_match")
    if filters.relations:
        matched.append("relations")

    if filters.review_state or filters.valid_at:
        related = [a for a in relevant if _assertion_parts(a)[0] == node.id]
        if filters.review_state:
            related = [a for a in related if _text(a, C1 + "reviewState") in filters.review_state]
            if not related:
                return MatchResult("no_match")
            matched.append("review_state")
        if filters.valid_at:
            intervals = intervals_by_id or {}
            statuses: list[str] = []
            for assertion in related:
                iri = next(
                    (v for v in _values(assertion, C1 + "validDuring") if isinstance(v, str)), None
                )
                statuses.append(
                    valid_at_status(intervals.get(iri) if iri else None, filters.valid_at)
                )
            if "match" in statuses:
                matched.append("valid_at")
            elif "indeterminate" in statuses and filters.include_unknown:
                return MatchResult("indeterminate", tuple(matched), "unknown_validity")
            else:
                return MatchResult("no_match")
    return MatchResult("match", tuple(matched))


def evaluate_assertion(
    node: NodeRecord,
    filters: AssertionFilters,
    *,
    interval: TimeInterval | None = None,
) -> MatchResult:
    """Evaluate one previously authorized assertion, with its authorized interval."""
    subject, predicate, obj = _assertion_parts(node)
    if filters.subject is not None and subject != filters.subject:
        return MatchResult("no_match")
    if filters.predicate is not None and predicate != filters.predicate:
        return MatchResult("no_match")
    if filters.object is not None and obj != filters.object:
        return MatchResult("no_match")
    if filters.review_state and _text(node, C1 + "reviewState") not in filters.review_state:
        return MatchResult("no_match")
    if filters.lifecycle and _text(node, C1 + "lifecycle") not in filters.lifecycle:
        return MatchResult("no_match")
    matched = tuple(
        name
        for name in ("subject", "predicate", "object", "review_state", "lifecycle")
        if getattr(filters, name)
    )
    if filters.valid_at:
        status = valid_at_status(interval, filters.valid_at)
        if status == "indeterminate" and not filters.include_unknown:
            return MatchResult("no_match")
        return MatchResult(
            status,
            matched + ("valid_at",),
            "unknown_validity" if status == "indeterminate" else None,
        )
    return MatchResult("match", matched)


def order_key(
    node: NodeRecord, order: Literal["id", "label", "recorded"], *, recorded_at: str | None = None
) -> tuple[str, str]:
    """Canonical IRI is the final tiebreak for every total order."""
    if order == "id":
        return node.id, node.id
    if order == "label":
        labels = [
            normalize(v.lexical)
            for v in _values(node, SKOS + "prefLabel")
            if isinstance(v, LiteralValue)
        ]
        return min(labels, default=""), node.id
    if order == "recorded":
        return recorded_at or "", node.id
    raise ValueError("unsupported order")
