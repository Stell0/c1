"""Lexical-first XSD temporal boundaries and derived comparison bounds.

The Gregorian arithmetic here accepts XSD 1.1 year zero, BCE years, and years
outside ``datetime``'s 1..9999 range. Derived timestamps never replace the
source lexical form. Bounds without a timezone are only provisional; callers
must inspect ``timezone_unknown`` before strict comparisons.
"""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

XSD = "http://www.w3.org/2001/XMLSchema#"
TEMPORAL_TYPES = frozenset(
    {XSD + "dateTimeStamp", XSD + "dateTime", XSD + "date", XSD + "gYearMonth", XSD + "gYear"}
)
NEGATIVE_INFINITY = "-∞"
POSITIVE_INFINITY = "+∞"

_YEAR = r"(?P<year>-?(?:[1-9][0-9]{3,}|0[0-9]{3}))"
_MONTH = r"-(?P<month>0[1-9]|1[0-2])"
_DAY = r"-(?P<day>0[1-9]|[12][0-9]|3[01])"
_TIME = r"T(?P<hour>[01][0-9]|2[0-4]):(?P<minute>[0-5][0-9]):(?P<second>[0-5][0-9](?:\.[0-9]+)?)"
_ZONE = r"(?P<zone>Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))?"
_PATTERNS = {
    XSD + "gYear": re.compile(_YEAR + _ZONE),
    XSD + "gYearMonth": re.compile(_YEAR + _MONTH + _ZONE),
    XSD + "date": re.compile(_YEAR + _MONTH + _DAY + _ZONE),
    XSD + "dateTime": re.compile(_YEAR + _MONTH + _DAY + _TIME + _ZONE),
    XSD + "dateTimeStamp": re.compile(_YEAR + _MONTH + _DAY + _TIME + _ZONE),
}


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if _leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _next_day(year: int, month: int, day: int) -> tuple[int, int, int]:
    if day < _days_in_month(year, month):
        return year, month, day + 1
    if month < 12:
        return year, month + 1, 1
    return year + 1, 1, 1


def _previous_day(year: int, month: int, day: int) -> tuple[int, int, int]:
    if day > 1:
        return year, month, day - 1
    if month > 1:
        return year, month - 1, _days_in_month(year, month - 1)
    return year - 1, 12, 31


def _year_text(year: int) -> str:
    return f"-{abs(year):04d}" if year < 0 else f"{year:04d}"


def _utc(
    year: int, month: int, day: int, hour: int, minute: int, second: str, zone: str | None
) -> str:
    if hour == 24:
        year, month, day = _next_day(year, month, day)
        hour = 0
    if zone not in (None, "Z"):
        sign = 1 if zone[0] == "+" else -1
        offset = sign * (int(zone[1:3]) * 60 + int(zone[4:6]))
        total = hour * 60 + minute - offset
        if total < 0:
            year, month, day = _previous_day(year, month, day)
        elif total >= 24 * 60:
            year, month, day = _next_day(year, month, day)
        hour, minute = divmod(total % (24 * 60), 60)
    return f"{_year_text(year)}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second}Z"


def temporal_bounds(lexical: str, datatype: str) -> tuple[str, str, bool]:
    """Validate an XSD temporal lexical form and return [earliest, latest].

    Coarse precision yields a half-open span. A dateTime is an exact point, so
    both bounds are the same. The source lexical form remains authoritative.
    """

    pattern = _PATTERNS.get(datatype)
    if pattern is None:
        raise PydanticCustomError("C1-IX-020", "Unsupported temporal datatype")
    match = pattern.fullmatch(lexical)
    if match is None:
        raise PydanticCustomError("C1-IX-021", "Invalid XSD temporal lexical form")
    parts = match.groupdict()
    year = int(parts["year"])
    month = int(parts.get("month") or 1)
    day = int(parts.get("day") or 1)
    if day > _days_in_month(year, month):
        raise PydanticCustomError("C1-IX-021", "Invalid day for month and year")
    zone = parts["zone"]
    if datatype == XSD + "dateTimeStamp" and zone is None:
        raise PydanticCustomError("C1-IX-021", "dateTimeStamp requires a timezone")
    unknown = zone is None
    if datatype in {XSD + "dateTime", XSD + "dateTimeStamp"}:
        hour = int(parts["hour"])
        minute = int(parts["minute"])
        second = parts["second"]
        assert second is not None
        if hour == 24 and (minute != 0 or re.fullmatch(r"00(?:\.0+)?", second) is None):
            raise PydanticCustomError("C1-IX-021", "24:00:00 must have zero minutes and seconds")
        value = _utc(year, month, day, hour, minute, second, zone)
        return value, value, unknown
    earliest = _utc(year, month, day, 0, 0, "00", zone)
    if datatype == XSD + "gYear":
        next_year, next_month, next_day = year + 1, 1, 1
    elif datatype == XSD + "gYearMonth":
        next_year, next_month, next_day = (year + 1, 1, 1) if month == 12 else (year, month + 1, 1)
    else:
        next_year, next_month, next_day = _next_day(year, month, day)
    latest = _utc(next_year, next_month, next_day, 0, 0, "00", zone)
    return earliest, latest, unknown


class TimeBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["known", "unknown", "unbounded"]
    lexical: str | None = None
    datatype: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state == "known":
            if self.lexical is None or self.datatype is None:
                raise PydanticCustomError(
                    "C1-IX-021", "Known boundary requires lexical and datatype"
                )
            temporal_bounds(self.lexical, self.datatype)
        elif self.lexical is not None or self.datatype is not None:
            raise PydanticCustomError("C1-IX-021", "Only known boundaries may carry a value")
        return self

    @property
    def earliest(self) -> str | None:
        if self.state != "known":
            return None
        assert self.lexical is not None and self.datatype is not None
        return temporal_bounds(self.lexical, self.datatype)[0]

    @property
    def latest(self) -> str | None:
        if self.state != "known":
            return None
        assert self.lexical is not None and self.datatype is not None
        return temporal_bounds(self.lexical, self.datatype)[1]

    @property
    def timezone_unknown(self) -> bool:
        if self.state != "known":
            return False
        assert self.lexical is not None and self.datatype is not None
        return temporal_bounds(self.lexical, self.datatype)[2]


class TimeInterval(BaseModel):
    """Half-open world-valid interval: start inclusive, end exclusive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: TimeBoundary
    end: TimeBoundary

    @property
    def start_earliest(self) -> str | None:
        return NEGATIVE_INFINITY if self.start.state == "unbounded" else self.start.earliest

    @property
    def start_latest(self) -> str | None:
        return NEGATIVE_INFINITY if self.start.state == "unbounded" else self.start.latest

    @property
    def end_earliest(self) -> str | None:
        return POSITIVE_INFINITY if self.end.state == "unbounded" else self.end.earliest

    @property
    def end_latest(self) -> str | None:
        return POSITIVE_INFINITY if self.end.state == "unbounded" else self.end.latest

    @property
    def timezone_unknown(self) -> bool:
        return self.start.timezone_unknown or self.end.timezone_unknown
