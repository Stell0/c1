"""Lossless supported RDF literal profile.

Lexical text is never converted through Python float or Decimal for storage.
The validators check XSD 1.1 lexical forms and BCP 47 tag syntax while
retaining the submitted spelling, apart from case-folding a language tag.
"""

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError
from rdflib import Literal, URIRef

from c1.model.time import TEMPORAL_TYPES, XSD, temporal_bounds

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDF_LANG_STRING = RDF + "langString"
XSD_STRING = XSD + "string"
SUPPORTED_DATATYPES = frozenset(
    {
        XSD_STRING,
        RDF_LANG_STRING,
        XSD + "boolean",
        XSD + "integer",
        XSD + "decimal",
        XSD + "double",
        XSD + "anyURI",
        *TEMPORAL_TYPES,
    }
)

_ALPHA = r"[A-Za-z]"
_ALNUM = r"[A-Za-z0-9]"
_LANGUAGE = rf"(?:{_ALPHA}{{2,3}}(?:-{_ALPHA}{{3}}){{0,3}}|{_ALPHA}{{4}}|{_ALPHA}{{5,8}})"
_SCRIPT = rf"(?:-{_ALPHA}{{4}})?"
_REGION = r"(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
_VARIANTS = rf"(?:-(?:{_ALNUM}{{5,8}}|[0-9]{_ALNUM}{{3}}))*"
_EXTENSIONS = rf"(?:-[0-9A-WY-Za-wy-z](?:-{_ALNUM}{{2,8}})+)*"
_PRIVATE = rf"(?:-x(?:-{_ALNUM}{{1,8}})+)?"
_LANGTAG = re.compile(_LANGUAGE + _SCRIPT + _REGION + _VARIANTS + _EXTENSIONS + _PRIVATE, re.I)
_PRIVATE_ONLY = re.compile(rf"x(?:-{_ALNUM}{{1,8}})+", re.I)
_VARIANT_TOKEN = re.compile(rf"(?:{_ALNUM}{{5,8}}|[0-9]{_ALNUM}{{3}})", re.I)
_GRANDFATHERED = frozenset(
    {
        "en-gb-oed",
        "i-ami",
        "i-bnn",
        "i-default",
        "i-enochian",
        "i-hak",
        "i-klingon",
        "i-lux",
        "i-mingo",
        "i-navajo",
        "i-pwn",
        "i-tao",
        "i-tay",
        "i-tsu",
        "sgn-be-fr",
        "sgn-be-nl",
        "sgn-ch-de",
        "art-lojban",
        "cel-gaulish",
        "no-bok",
        "no-nyn",
        "zh-guoyu",
        "zh-hakka",
        "zh-min",
        "zh-min-nan",
        "zh-xiang",
    }
)

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_DOUBLE = re.compile(r"(?:[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?INF|NaN)")
_XML_WS = re.compile(r"[\x09\x0a\x0d\x20]+")


def normalize_language(tag: str) -> str:
    """Validate RFC 5646 syntax and unique subtags, then lowercase for RDF."""

    lowered = tag.lower()
    if lowered in _GRANDFATHERED or _PRIVATE_ONLY.fullmatch(tag):
        return lowered
    if _LANGTAG.fullmatch(tag) is None:
        raise PydanticCustomError("C1-IX-022", "Invalid BCP 47 language tag")
    parts = lowered.split("-")
    position = 1
    if len(parts[0]) in {2, 3}:
        for _ in range(3):
            if position < len(parts) and re.fullmatch(r"[a-z]{3}", parts[position]):
                position += 1
            else:
                break
    if position < len(parts) and re.fullmatch(r"[a-z]{4}", parts[position]):
        position += 1
    if position < len(parts) and re.fullmatch(r"(?:[a-z]{2}|[0-9]{3})", parts[position]):
        position += 1
    variants: set[str] = set()
    while position < len(parts) and _VARIANT_TOKEN.fullmatch(parts[position]):
        variant = parts[position]
        if variant in variants:
            raise PydanticCustomError("C1-IX-022", "Repeated BCP 47 variant")
        variants.add(variant)
        position += 1
    extensions: set[str] = set()
    while position < len(parts) and parts[position] != "x":
        singleton = parts[position]
        if singleton in extensions:
            raise PydanticCustomError("C1-IX-022", "Repeated BCP 47 extension singleton")
        extensions.add(singleton)
        position += 1
        while position < len(parts) and len(parts[position]) > 1:
            position += 1
    return lowered


def _collapsed(text: str) -> str:
    return _XML_WS.sub(" ", text).strip(" ")


def validate_lexical(lexical: str, datatype: str) -> None:
    if datatype not in SUPPORTED_DATATYPES:
        raise PydanticCustomError("C1-IX-020", "Unsupported literal datatype")
    if datatype in {XSD_STRING, RDF_LANG_STRING, XSD + "anyURI"}:
        return
    value = _collapsed(lexical)
    if datatype == XSD + "boolean":
        valid = value in {"true", "false", "1", "0"}
    elif datatype == XSD + "integer":
        valid = _INTEGER.fullmatch(value) is not None
    elif datatype == XSD + "decimal":
        valid = _DECIMAL.fullmatch(value) is not None
    elif datatype == XSD + "double":
        valid = _DOUBLE.fullmatch(value) is not None
    elif datatype in TEMPORAL_TYPES:
        temporal_bounds(value, datatype)
        return
    else:
        valid = False
    if not valid:
        raise PydanticCustomError("C1-IX-021", "Invalid literal lexical form")


class LiteralValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lexical: str
    datatype: str
    language: str | None = None

    @model_validator(mode="after")
    def validate_literal(self) -> Self:
        if self.language is not None:
            if self.datatype != RDF_LANG_STRING:
                raise PydanticCustomError(
                    "C1-IX-022", "A language tag requires rdf:langString datatype"
                )
            object.__setattr__(self, "language", normalize_language(self.language))
        elif self.datatype == RDF_LANG_STRING:
            raise PydanticCustomError("C1-IX-022", "rdf:langString requires a language tag")
        validate_lexical(self.lexical, self.datatype)
        return self

    def to_rdf(self) -> Literal:
        if self.language is not None:
            return Literal(self.lexical, lang=self.language, normalize=False)
        return Literal(self.lexical, datatype=URIRef(self.datatype), normalize=False)

    @classmethod
    def from_rdf(cls, literal: Literal) -> Self:
        if literal.language is not None:
            return cls(lexical=str(literal), datatype=RDF_LANG_STRING, language=literal.language)
        return cls(lexical=str(literal), datatype=str(literal.datatype or XSD_STRING))
