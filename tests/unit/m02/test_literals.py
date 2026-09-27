import pytest
from pydantic import ValidationError
from rdflib import Literal

from c1.model.literals import RDF_LANG_STRING, XSD_STRING, LiteralValue
from c1.model.time import XSD


@pytest.mark.parametrize(
    ("datatype", "lexical"),
    [
        (XSD_STRING, " exact  text "),
        (XSD + "boolean", "1"),
        (XSD + "integer", "+00012"),
        (XSD + "decimal", "123456789123456789.00000000000001"),
        (XSD + "double", "-1.23E+45"),
        (XSD + "double", "NaN"),
        (XSD + "anyURI", "urn:c1:sample"),
        (XSD + "gYear", "10000Z"),
        (XSD + "gYearMonth", "2020-02"),
        (XSD + "date", "2020-02-29Z"),
        (XSD + "dateTime", "2020-02-29T10:20:30.123456789"),
        (XSD + "dateTimeStamp", "2020-02-29T10:20:30+02:00"),
    ],
)
def test_supported_literal_preserves_lexical_rdf_form(datatype: str, lexical: str) -> None:
    value = LiteralValue(lexical=lexical, datatype=datatype)
    restored = LiteralValue.from_rdf(value.to_rdf())
    assert restored == value
    assert str(restored.to_rdf()) == lexical


def test_language_literal_preserves_text_and_lowercases_tag() -> None:
    value = LiteralValue(lexical=" Batterie ", datatype=RDF_LANG_STRING, language="DE-ch")
    assert value.language == "de-ch"
    assert LiteralValue.from_rdf(value.to_rdf()) == value
    assert LiteralValue.from_rdf(Literal("text", lang="en")).datatype == RDF_LANG_STRING


@pytest.mark.parametrize(
    "language", ["sl-rozaj-rozaj", "en-1901-1901", "en-u-ca-gregory-u-nu-latn"]
)
def test_repeated_bcp47_variant_or_extension_rejected(language: str) -> None:
    with pytest.raises(ValidationError) as caught:
        LiteralValue(lexical="text", datatype=RDF_LANG_STRING, language=language)
    assert caught.value.errors()[0]["type"] == "C1-IX-022"


def test_distinct_bcp47_extensions_remain_valid() -> None:
    value = LiteralValue(lexical="text", datatype=RDF_LANG_STRING, language="en-u-ca-gregory-a-foo")
    assert value.language == "en-u-ca-gregory-a-foo"


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ({"lexical": "x", "datatype": XSD + "duration"}, "C1-IX-020"),
        ({"lexical": "12e3", "datatype": XSD + "decimal"}, "C1-IX-021"),
        ({"lexical": "2021-02-29", "datatype": XSD + "date"}, "C1-IX-021"),
        ({"lexical": "2020-01-01T00:00:00", "datatype": XSD + "dateTimeStamp"}, "C1-IX-021"),
        ({"lexical": "text", "datatype": XSD_STRING, "language": "en"}, "C1-IX-022"),
        ({"lexical": "text", "datatype": RDF_LANG_STRING}, "C1-IX-022"),
        ({"lexical": "text", "datatype": RDF_LANG_STRING, "language": "en_XX"}, "C1-IX-022"),
    ],
)
def test_invalid_literal_has_stable_code(value: dict[str, str], code: str) -> None:
    with pytest.raises(ValidationError) as caught:
        LiteralValue.model_validate(value)
    assert caught.value.errors()[0]["type"] == code
