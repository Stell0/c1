import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from c1.model.time import XSD, TimeBoundary, TimeInterval

VECTORS = Path(__file__).parent / "vectors" / "time.json"


def test_time_bounds_vectors_and_lexical_preservation() -> None:
    for vector in json.loads(VECTORS.read_text()):
        boundary = TimeBoundary(
            state="known", lexical=vector["lexical"], datatype=XSD + vector["datatype"]
        )
        assert boundary.earliest == vector["earliest"]
        assert boundary.latest == vector["latest"]
        assert boundary.timezone_unknown is vector["timezone_unknown"]
        assert boundary.model_dump() == {
            "state": "known",
            "lexical": vector["lexical"],
            "datatype": XSD + vector["datatype"],
        }


def test_half_open_unknown_and_unbounded_are_distinct() -> None:
    known = TimeBoundary(state="known", lexical="2020", datatype=XSD + "gYear")
    unknown = TimeBoundary(state="unknown")
    unbounded = TimeBoundary(state="unbounded")
    assert unknown.earliest is None
    assert unbounded.earliest is None
    assert TimeInterval(start=unknown, end=known).start_earliest is None
    interval = TimeInterval(start=unbounded, end=unbounded)
    assert interval.start_earliest == "-∞"
    assert interval.end_latest == "+∞"
    assert interval.model_dump()["start"]["state"] == "unbounded"


@pytest.mark.parametrize(
    "lexical",
    ["2021-02-29", "2020-13-01", "2020-01-00", "2020-01-01+14:30"],
)
def test_invalid_dates_rejected(lexical: str) -> None:
    with pytest.raises(ValidationError) as caught:
        TimeBoundary(state="known", lexical=lexical, datatype=XSD + "date")
    assert caught.value.errors()[0]["type"] == "C1-IX-021"


def test_end_of_day_and_bce_arithmetic() -> None:
    end_of_day = TimeBoundary(
        state="known", lexical="2020-12-31T24:00:00Z", datatype=XSD + "dateTimeStamp"
    )
    assert end_of_day.earliest == "2021-01-01T00:00:00Z"
    bce = TimeBoundary(state="known", lexical="-0004Z", datatype=XSD + "gYear")
    assert bce.latest == "-0003-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        TimeBoundary(state="known", lexical="2020-12-31T24:01:00Z", datatype=XSD + "dateTime")


def test_end_of_day_rejects_fraction_too_small_for_float() -> None:
    tiny_fraction = "0" * 400 + "1"
    with pytest.raises(ValidationError) as caught:
        TimeBoundary(
            state="known",
            lexical=f"2020-12-31T24:00:00.{tiny_fraction}Z",
            datatype=XSD + "dateTimeStamp",
        )
    assert caught.value.errors()[0]["type"] == "C1-IX-021"
