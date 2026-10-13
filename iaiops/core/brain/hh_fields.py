"""Cell-level parsing for supplier half-hourly files: headers, dates, values, flags.

Every function here answers one question about one cell and says "I do not know"
rather than guessing. Three of those refusals carry the weight of the whole
feature:

* **A blank or unreadable value is missing, never zero.** A zero is a reading —
  "the site used nothing" — and a gap filled with zeros makes the base load look
  lower and the out-of-hours waste look smaller than they are.
* **Dates are UK day-first only.** ``01/13/2026`` is rejected, not read as
  13 January: a supplier file that is month-first would otherwise be silently
  shuffled for the first twelve days of every month.
* **No read-type flag means "unknown", not "actual".** Claiming a file is all
  actual reads because nobody said otherwise is the flattering direction.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime

#: Read-type codes that mean a measured reading.
ACTUAL_CODES = frozenset({"A", "ACTUAL", "M", "MEASURED"})
#: Read-type codes that mean the supplier or data collector estimated the value.
ESTIMATED_CODES = frozenset({"E", "EST", "ESTIMATE", "ESTIMATED"})

UNITS = ("kwh", "wh", "kw")

_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y")
_TIME_FORMATS = ("%H:%M", "%H:%M:%S")
_STAMP_FORMATS = tuple(f"{d} {t}" for d in _DATE_FORMATS for t in _TIME_FORMATS)

_PERIOD_RE = re.compile(r"^(?:hh|p|period|hh ?period|half ?hour)?[ _-]?0?(\d{1,2})$")
_CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}$")
_FLAG_WORDS = ("flag", "status", "est", "type", "quality", "actual")


def norm(header: str) -> str:
    """Lower-cased, whitespace-collapsed header text."""
    return " ".join(header.strip().lower().split())


def is_flag_header(header: str) -> bool:
    h = norm(header)
    return any(word in h for word in _FLAG_WORDS)


def is_meter_header(header: str) -> bool:
    h = norm(header)
    return "mpan" in h or h in {"meter", "meter id", "meter_id", "meter serial", "msn", "site"}


def is_period_header(header: str) -> bool:
    h = norm(header)
    if is_flag_header(h):
        return False
    return bool(_PERIOD_RE.match(h) or _CLOCK_RE.match(h))


def is_date_header(header: str) -> bool:
    h = norm(header)
    return "date" in h and "time" not in h and "stamp" not in h


def is_time_header(header: str) -> bool:
    h = norm(header)
    return h in {"time", "period time", "start time", "end time", "interval time"}


def is_stamp_header(header: str) -> bool:
    h = norm(header)
    return "timestamp" in h or "datetime" in h or ("date" in h and "time" in h)


def is_value_header(header: str) -> bool:
    h = norm(header)
    words = ("kwh", "wh", "kw", "consumption", "usage", "value", "reading", "energy", "demand")
    return not is_flag_header(h) and any(w in h for w in words)


def unit_from_header(header: str) -> str | None:
    """The unit a header states, or ``None`` when it states none."""
    h = norm(header)
    if "kwh" in h:
        return "kwh"
    if re.search(r"(?<![a-z])wh(?![a-z])", h):
        return "wh"
    if re.search(r"(?<![a-z])kw(?![a-z])", h):
        return "kw"
    return None


def to_kwh(value: float, unit: str) -> float:
    """Convert one half-hour's value to kWh. kW is the half-hour's average demand."""
    if unit == "wh":
        return value / 1000.0
    if unit == "kw":
        return value / 2.0
    return value


def parse_value(cell: str) -> float | None:
    """A finite number, or ``None`` for blank / unreadable / NaN / inf."""
    text = cell.strip().replace(",", "")
    if not text:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def parse_day(cell: str) -> date | None:
    """A UK day-first or ISO date, or ``None``."""
    text = cell.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_clock(cell: str) -> tuple[int, int] | None:
    """``HH:MM`` (``24:00`` allowed) as hour/minute, or ``None``."""
    text = cell.strip()
    for fmt in _TIME_FORMATS:
        if text.startswith("24:00"):
            return 24, 0
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.hour, parsed.minute
    return None


def parse_stamp(cell: str) -> datetime | None:
    """A timestamp: ISO-8601 (offset honoured) or UK day-first. Naive = UK local."""
    text = cell.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _STAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def classify_flag(cell: str | None) -> tuple[bool | None, str | None]:
    """``(estimated, unrecognised_code)`` for one read-type cell.

    Blank → ``(None, None)``: not stated. An unrecognised code is treated as
    estimated — it is at least not known to be a measurement.
    """
    if cell is None:
        return None, None
    code = cell.strip().upper()
    if not code:
        return None, None
    if code in ACTUAL_CODES:
        return False, None
    if code in ESTIMATED_CODES:
        return True, None
    return True, code[:16]


__all__ = [
    "ACTUAL_CODES",
    "ESTIMATED_CODES",
    "UNITS",
    "classify_flag",
    "is_date_header",
    "is_flag_header",
    "is_meter_header",
    "is_period_header",
    "is_stamp_header",
    "is_time_header",
    "is_value_header",
    "norm",
    "parse_clock",
    "parse_day",
    "parse_stamp",
    "parse_value",
    "to_kwh",
    "unit_from_header",
]
