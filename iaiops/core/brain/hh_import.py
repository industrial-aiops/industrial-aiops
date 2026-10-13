"""Read a supplier half-hourly (HH) electricity CSV into settlement intervals.

UK suppliers and data collectors export HH data in two shapes, and this reads both:

* **wide** — one row per meter per local day: a date, optionally the MPAN, and
  46–50 period columns. Column *i* is the *i*-th half hour from LOCAL midnight,
  so on the spring clock-change day only 46 periods exist and on the autumn day 50.
* **long** — one row per half hour: a timestamp (or a date and a time column) and
  a consumption value. Naive times are UK local; an ISO offset is honoured.

What comes out is a list of :class:`Interval` in UTC — one per half hour that the
file actually measured. Anything the file did not measure is ABSENT, not zero, and
every decision the parser had to make on the reader's behalf is listed in
``assumptions`` so a report can repeat it.

Pure: text in, frozen result out. No file, network or model access.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from iaiops.core.brain import hh_fields as f
from iaiops.core.brain import uk_clock

MAX_TEXT_BYTES = 50 * 1024 * 1024
MAX_INTERVALS = 2_000_000
UNNAMED_METER = "(unnamed)"
_HALF_HOUR = timedelta(minutes=30)
_MAX_WARNING_KINDS = 20
#: Always present in ``counts`` (as 0 when nothing happened), so a reader can tell
#: "no rows were rejected" from "this file format never counts rejections".
_COUNT_KEYS = (
    "rows_read",
    "intervals",
    "rows_rejected",
    "blank_or_non_numeric",
    "negative_rejected",
    "duplicate_conflicting",
    "duplicate_identical",
    "missing_long_day_periods",
    "unrecognised_flags",
)


@dataclass(frozen=True)
class Interval:
    """One measured half hour. ``estimated`` is ``None`` when the file did not say."""

    start_utc: datetime
    kwh: float
    estimated: bool | None
    meter: str


@dataclass(frozen=True)
class ParseResult:
    intervals: tuple[Interval, ...]
    meters: tuple[str, ...]
    layout: str
    unit: str
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    counts: Mapping[str, int]


@dataclass(frozen=True)
class _Reading:
    meter: str
    start_utc: datetime
    kwh: float
    estimated: bool | None


class _Tally:
    """Counts and de-duplicated warnings collected while parsing one file."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.warnings: Counter[str] = Counter()
        self.codes: Counter[str] = Counter()

    def warn(self, message: str) -> None:
        if message in self.warnings or len(self.warnings) < _MAX_WARNING_KINDS:
            self.warnings[message] += 1

    def value(self, cell: str, unit: str) -> float | None:
        number = f.parse_value(cell)
        if number is None:
            self.counts["blank_or_non_numeric"] += 1
            return None
        if number < 0:
            self.counts["negative_rejected"] += 1
            self.warn("negative value rejected (export or a meter fault — not consumption)")
            return None
        return f.to_kwh(number, unit)

    def flag(self, cell: str | None) -> bool | None:
        estimated, code = f.classify_flag(cell)
        if code is not None:
            self.codes[code] += 1
        return estimated


def _check_options(unit: str, timestamp_marks: str) -> None:
    if unit not in ("auto", *f.UNITS):
        raise ValueError(f"unit must be auto, kwh, wh or kw — got {unit!r}")
    if timestamp_marks not in ("start", "end"):
        raise ValueError(f"timestamp_marks must be 'start' or 'end' — got {timestamp_marks!r}")


def _rows(text: str) -> list[list[str]]:
    if len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        raise ValueError(f"file too large (cap {MAX_TEXT_BYTES // (1024 * 1024)} MiB)")
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("no data: the file needs a header row and at least one data row")
    return rows


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


# --- wide -----------------------------------------------------------------------


def _wide_columns(header: list[str]) -> dict | None:
    date_col = next((i for i, h in enumerate(header) if f.is_date_header(h)), None)
    periods = [i for i, h in enumerate(header) if f.is_period_header(h)]
    if date_col is None or not 46 <= len(periods) <= 50:
        return None
    period_flags = {
        p: p + 1 for p in periods if p + 1 < len(header) and f.is_flag_header(header[p + 1])
    }
    row_flag = next(
        (i for i, h in enumerate(header) if f.is_flag_header(h) and i < periods[0]), None
    )
    meter = next((i for i, h in enumerate(header) if f.is_meter_header(h)), None)
    return {
        "date": date_col,
        "periods": periods,
        "period_flags": period_flags,
        "row_flag": row_flag,
        "meter": meter,
        "has_flags": bool(period_flags) or row_flag is not None,
    }


def _wide_row(row: list[str], cols: dict, unit: str, tally: _Tally) -> list[_Reading]:
    day = f.parse_day(_cell(row, cols["date"]))
    if day is None:
        tally.counts["rows_rejected"] += 1
        tally.warn("row rejected: date not UK day-first (dd/mm/yyyy) or ISO")
        return []
    expected = uk_clock.periods_in_day(day)
    periods = cols["periods"]
    beyond = [p for p in periods[expected:] if _cell(row, p).strip()]
    if beyond:
        tally.counts["rows_rejected"] += 1
        tally.warn(
            f"row rejected: {day.isoformat()} has {expected} half hours but values in "
            f"{len(periods)} period columns"
        )
        return []
    if len(periods) < expected:
        tally.counts["missing_long_day_periods"] += expected - len(periods)
        tally.warn(f"{day.isoformat()} has {expected} half hours; the file carries {len(periods)}")
    meter = _cell(row, cols["meter"]).strip() or UNNAMED_METER
    midnight = uk_clock.local_midnight_utc(day)
    row_flag = _cell(row, cols["row_flag"]) if cols["row_flag"] is not None else None
    out = []
    for i, p in enumerate(periods[:expected]):
        kwh = tally.value(_cell(row, p), unit)
        if kwh is None:
            continue
        flag_col = cols["period_flags"].get(p)
        flag = _cell(row, flag_col) if flag_col is not None else row_flag
        out.append(_Reading(meter, midnight + i * _HALF_HOUR, kwh, tally.flag(flag)))
    return out


# --- long -----------------------------------------------------------------------


def _long_columns(header: list[str]) -> dict | None:
    stamp = next((i for i, h in enumerate(header) if f.is_stamp_header(h)), None)
    day = next((i for i, h in enumerate(header) if f.is_date_header(h)), None)
    clock = next((i for i, h in enumerate(header) if f.is_time_header(h)), None)
    value = next((i for i, h in enumerate(header) if f.is_value_header(h)), None)
    if value is None or (stamp is None and (day is None or clock is None)):
        return None
    flag = next((i for i, h in enumerate(header) if f.is_flag_header(h)), None)
    meter = next((i for i, h in enumerate(header) if f.is_meter_header(h)), None)
    return {"stamp": stamp, "day": day, "clock": clock, "value": value, "flag": flag,
            "meter": meter, "has_flags": flag is not None}  # fmt: skip


def _long_stamp(row: list[str], cols: dict) -> datetime | None:
    if cols["stamp"] is not None:
        return f.parse_stamp(_cell(row, cols["stamp"]))
    day = f.parse_day(_cell(row, cols["day"]))
    clock = f.parse_clock(_cell(row, cols["clock"]))
    if day is None or clock is None:
        return None
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=clock[0], minutes=clock[1])


def _long_row(row, cols, unit, marks, seen, tally) -> list[_Reading]:
    stamp = _long_stamp(row, cols)
    meter = _cell(row, cols["meter"]).strip() or UNNAMED_METER
    if stamp is None:
        tally.counts["rows_rejected"] += 1
        tally.warn("row rejected: timestamp not ISO-8601 or UK day-first")
        return []
    if stamp.tzinfo is not None:
        utc = stamp.astimezone(UTC)
    else:
        fold = 1 if (meter, stamp) in seen else 0
        seen.add((meter, stamp))
        utc = uk_clock.local_to_utc(stamp, fold=fold)
        if utc is None:
            tally.counts["rows_rejected"] += 1
            tally.warn("row rejected: local time inside the spring clock-change gap")
            return []
    if utc.minute not in (0, 30) or utc.second or utc.microsecond:
        tally.counts["rows_rejected"] += 1
        tally.warn("row rejected: timestamp not on the half-hour grid")
        return []
    start = utc - _HALF_HOUR if marks == "end" else utc
    kwh = tally.value(_cell(row, cols["value"]), unit)
    if kwh is None:
        return []
    flag = _cell(row, cols["flag"]) if cols["flag"] is not None else None
    return [_Reading(meter, start, kwh, tally.flag(flag))]


# --- assembly -------------------------------------------------------------------


def _dedupe(readings: list[_Reading], tally: _Tally) -> tuple[Interval, ...]:
    first: dict[tuple[str, datetime], _Reading] = {}
    for r in readings:
        key = (r.meter, r.start_utc)
        kept = first.get(key)
        if kept is None:
            first[key] = r
        elif abs(kept.kwh - r.kwh) > 1e-9:
            tally.counts["duplicate_conflicting"] += 1
        else:
            tally.counts["duplicate_identical"] += 1
    if tally.counts["duplicate_conflicting"]:
        tally.warn("the same half hour appears twice with different values — kept the first")
    ordered = sorted(first.values(), key=lambda r: (r.meter, r.start_utc))
    return tuple(Interval(r.start_utc, r.kwh, r.estimated, r.meter) for r in ordered)


def _resolve_unit(unit: str, header_unit: str | None, assumptions: list[str]) -> str:
    if unit != "auto":
        assumptions.append(f"unit given by the caller: {unit}")
        return unit
    if header_unit is not None:
        assumptions.append(f"unit read from the header: {header_unit}")
        return header_unit
    assumptions.append("the header states no unit; values assumed to be kWh per half hour")
    return "kwh"


def parse_hh_csv(text: str, *, unit: str = "auto", timestamp_marks: str = "start") -> ParseResult:
    """Parse a supplier HH CSV (wide or long) into UTC half-hour intervals.

    ``timestamp_marks`` applies to the long layout: whether a row's time labels the
    START of its half hour (00:00 = first period) or the END (00:30 = first period).
    Suppliers differ and the file rarely says, so the choice is recorded.
    """
    _check_options(unit, timestamp_marks)
    if not text or not text.strip():
        raise ValueError("no data: the file is empty")
    rows = _rows(text)
    header, body = rows[0], rows[1:]
    tally = _Tally()
    assumptions: list[str] = []
    readings: list[_Reading] = []
    cols = _wide_columns(header)
    if cols is not None:
        layout = "wide"
        resolved = _resolve_unit(unit, None, assumptions)
        assumptions.append("period columns count half hours from UK local midnight")
        for row in body:
            readings.extend(_wide_row(row, cols, resolved, tally))
    else:
        cols = _long_columns(header)
        if cols is None:
            raise ValueError(
                "unrecognised layout: expected a date column plus 46–50 half-hour columns "
                "(wide), or a timestamp / date+time column plus a kWh column (long)"
            )
        layout = "long"
        resolved = _resolve_unit(unit, f.unit_from_header(header[cols["value"]]), assumptions)
        assumptions.append(f"each timestamp marks the {timestamp_marks} of its half hour")
        assumptions.append("timestamps without an offset are UK local time (GMT/BST)")
        seen: set = set()
        for row in body:
            readings.extend(_long_row(row, cols, resolved, timestamp_marks, seen, tally))
        if resolved == "kw":
            assumptions.append("kW values are half-hour average demand; kWh = kW ÷ 2")
    if len(readings) > MAX_INTERVALS:
        raise ValueError(f"too many intervals ({len(readings)}; cap {MAX_INTERVALS})")
    if not cols["has_flags"]:
        assumptions.append("the file carries no actual/estimated flag; read type is unknown")
    if tally.codes:
        codes = ", ".join(sorted(tally.codes))
        tally.warn(f"unrecognised read-type code(s) {codes} treated as estimated")
        tally.counts["unrecognised_flags"] = sum(tally.codes.values())
    intervals = _dedupe(readings, tally)
    tally.counts["rows_read"] = len(body)
    tally.counts["intervals"] = len(intervals)
    warnings = tuple(m if n == 1 else f"{m} (×{n})" for m, n in tally.warnings.items())
    return ParseResult(
        intervals=intervals,
        meters=tuple(sorted({iv.meter for iv in intervals})),
        layout=layout,
        unit=resolved,
        assumptions=tuple(assumptions),
        warnings=warnings,
        counts=MappingProxyType({**dict.fromkeys(_COUNT_KEYS, 0), **tally.counts}),
    )


__all__ = ["MAX_INTERVALS", "MAX_TEXT_BYTES", "Interval", "ParseResult", "parse_hh_csv"]
