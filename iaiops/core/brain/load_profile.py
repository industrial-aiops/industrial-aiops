"""What a site's half-hourly consumption says: base load, out-of-hours use, peaks.

Input is the list of :class:`~iaiops.core.brain.hh_import.Interval` a supplier file
produced. Output is the handful of figures an energy consultant uses to find
waste in a small site — and nothing it would have to guess:

* **Totals are measured totals.** Missing half hours are counted and reported as
  missing; nothing is scaled up to "fill" them. A report that extrapolated would
  print a bill-sized number from half the data, in whichever direction the gap
  happened to fall.
* **Day-type averages use complete days only.** A Monday with six missing hours
  averaged in with full ones would make Mondays look cheaper than they are.
* **Base load is the median demand overnight** (00:00–05:00 local by default) —
  the "always on" floor. The out-of-hours figure above it is labelled an
  indication of opportunity, never a guaranteed saving.

Pure: no I/O, no model. Times are analysed on the UK local clock.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from statistics import median
from types import MappingProxyType

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval
from iaiops.core.brain.load_profile_findings import findings, warnings

DEFAULT_OPERATING_HOURS = "mon-fri 08:00-18:00"
DEFAULT_NIGHT = ("00:00", "05:00")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_HALF_HOUR = timedelta(minutes=30)
_SEGMENT_RE = re.compile(r"^([a-z,\-]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2})$")
OPPORTUNITY_NOTE = (
    "Out-of-hours consumption above the overnight base load: an indication of "
    "opportunity, not a guaranteed saving — some of it may be needed (cleaning, "
    "security lighting, frost protection, refrigeration)."
)


def _minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    h, m = int(hour), int(minute)
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(f"not a clock time: {clock!r}")
    return h * 60 + m


def parse_days(token: str) -> list[int]:
    out: list[int] = []
    for part in token.split(","):
        ends = part.split("-")
        if len(ends) > 2 or any(e not in _DAYS for e in ends):
            raise ValueError(f"unknown day {part!r}; use mon..sun, ranges like mon-fri")
        first, last = _DAYS.index(ends[0]), _DAYS.index(ends[-1])
        if last < first:
            raise ValueError(f"day range runs backwards: {part!r}")
        out.extend(range(first, last + 1))
    return out


def parse_operating_hours(spec: str) -> Mapping[int, tuple[tuple[int, int], ...]]:
    """``"mon-fri 08:00-18:00; sat 09:00-13:00"`` → weekday → (start, end) minutes.

    Days not named are closed. Hours may not cross midnight — write two segments.
    """
    text = (spec or DEFAULT_OPERATING_HOURS).strip().lower()
    hours: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for segment in filter(None, (s.strip() for s in text.split(";"))):
        match = _SEGMENT_RE.match(segment)
        if match is None:
            raise ValueError(f"operating hours segment {segment!r}: expected 'mon-fri 08:00-18:00'")
        start, end = _minutes(match.group(2)), _minutes(match.group(3))
        if end <= start:
            raise ValueError(f"segment {segment!r} ends before it starts; split at midnight")
        for day in parse_days(match.group(1)):
            hours[day].append((start, end))
    return MappingProxyType({d: tuple(sorted(hours.get(d, []))) for d in range(7)})


def _instant(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is not None:
        return stamp.astimezone(UTC)
    utc = uk_clock.local_to_utc(stamp)
    if utc is None:
        raise ValueError(f"{value} does not exist on the UK clock (spring change)")
    return utc


def resolve_window(intervals: Sequence[Interval], since, until) -> tuple[datetime, datetime, str]:
    lo, hi = _instant(since), _instant(until)
    if (lo is None) != (hi is None):
        raise ValueError("since and until go together — one alone leaves the window undefined")
    if lo is not None and hi is not None:
        if hi <= lo:
            raise ValueError("until must be after since")
        return lo, hi, "requested"
    return intervals[0].start_utc, intervals[-1].start_utc + _HALF_HOUR, "data_span"


def _in_hours(local: datetime, hours, holidays: frozenset[date]) -> bool:
    if local.date() in holidays:
        return False
    minute = local.hour * 60 + local.minute
    return any(start <= minute < end for start, end in hours[local.weekday()])


def _read_type(intervals: Sequence[Interval], total: float) -> tuple[str, float | None, float]:
    flagged = [iv for iv in intervals if iv.estimated is not None]
    estimated_kwh = sum(iv.kwh for iv in intervals if iv.estimated)
    if not flagged:
        return "unknown", None, 0.0
    kind = "flagged" if len(flagged) == len(intervals) else "partly_flagged"
    share = round(100.0 * estimated_kwh / total, 2) if total > 0 else 0.0
    return kind, share, estimated_kwh


def _daily(intervals: Sequence[Interval], holidays: frozenset[date]) -> list[dict]:
    per_day: dict[date, list[float]] = defaultdict(list)
    for iv in intervals:
        per_day[uk_clock.to_local(iv.start_utc).date()].append(iv.kwh)
    rows = []
    for day in sorted(per_day):
        values = per_day[day]
        expected = uk_clock.periods_in_day(day)
        closed = day.weekday() >= 5 or day in holidays
        rows.append({
            "date": day.isoformat(), "weekday": _DAY_NAMES[day.weekday()],
            "kwh": round(sum(values), 3), "periods_measured": len(values),
            "periods_in_day": expected, "complete": len(values) == expected,
            "day_type": "weekend" if closed else "weekday",
        })  # fmt: skip
    return rows


def _day_types(daily: list[dict]) -> dict:
    out = {}
    for kind in ("weekday", "weekend"):
        full = [d["kwh"] for d in daily if d["day_type"] == kind and d["complete"]]
        out[kind] = {
            "avg_daily_kwh": round(sum(full) / len(full), 3) if full else None,
            "full_days": len(full),
        }
    out["note"] = "complete days only; 'weekend' includes declared holidays"
    return out


def _heatmap(locals_kw: Iterable[tuple[datetime, float]]) -> dict:
    sums = [[0.0] * 48 for _ in range(7)]
    counts = [[0] * 48 for _ in range(7)]
    for local, kw in locals_kw:
        slot = (local.hour * 60 + local.minute) // 30
        sums[local.weekday()][slot] += kw
        counts[local.weekday()][slot] += 1
    mean = [
        [round(sums[d][s] / counts[d][s], 3) if counts[d][s] else None for s in range(48)]
        for d in range(7)
    ]
    return {"weekdays": list(_DAY_NAMES), "slots": 48, "mean_kw": mean}


def _single_meter(intervals: Sequence[Interval]) -> list[Interval]:
    meters = {iv.meter for iv in intervals}
    if not intervals:
        raise ValueError("no half-hour intervals to analyse")
    if len(meters) > 1:
        raise ValueError(f"intervals from {len(meters)} meters; analyse one meter at a time")
    return sorted(intervals, key=lambda iv: iv.start_utc)


def analyse_load_profile(
    intervals: Sequence[Interval],
    *,
    operating_hours: str = DEFAULT_OPERATING_HOURS,
    holidays: Iterable[str | date] = (),
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    night: tuple[str, str] = DEFAULT_NIGHT,
) -> dict:
    """Profile ONE meter's half-hourly consumption over a window."""
    ordered = _single_meter(intervals)
    hours = parse_operating_hours(operating_hours)
    closed = frozenset(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in holidays)
    start, end, basis = resolve_window(ordered, since, until)
    inside = [iv for iv in ordered if start <= iv.start_utc < end]
    if not inside:
        raise ValueError("no measured half hours inside the requested window")
    expected = int((end - start) / _HALF_HOUR)
    locals_kw = [(uk_clock.to_local(iv.start_utc), iv.kwh * 2.0) for iv in inside]
    total = sum(iv.kwh for iv in inside)
    read_type, est_share, est_kwh = _read_type(inside, total)

    night_lo, night_hi = _minutes(night[0]), _minutes(night[1])
    night_kw = [kw for loc, kw in locals_kw if night_lo <= loc.hour * 60 + loc.minute < night_hi]
    base = round(median(night_kw), 3) if night_kw else None
    peak_local, peak_kw = max(locals_kw, key=lambda pair: pair[1])
    ooh = [kw for loc, kw in locals_kw if not _in_hours(loc, hours, closed)]
    ooh_kwh = sum(ooh) / 2.0
    above = None if base is None else round(sum(max(0.0, kw - base) for kw in ooh) / 2.0, 3)
    daily = _daily(inside, closed)
    mean_kw = total * 2.0 / len(inside)

    result = {
        "meter": ordered[0].meter,
        "window": {
            "start_utc": start.isoformat(), "end_utc": end.isoformat(), "basis": basis,
            "start_local": uk_clock.to_local(start).isoformat(sep=" "),
            "end_local": uk_clock.to_local(end).isoformat(sep=" "),
        },
        "coverage": {
            "expected_periods": expected, "measured_periods": len(inside),
            "missing_periods": expected - len(inside),
            "coverage_pct": round(100.0 * len(inside) / expected, 2),
        },
        "consumption": {
            "measured_kwh": round(total, 3), "estimated_kwh": round(est_kwh, 3),
            "estimated_share_pct": est_share, "read_type": read_type,
            "note": "measured half hours only — gaps are not filled or scaled up",
        },
        "peak": {"kw": round(peak_kw, 3), "at_local": peak_local.isoformat(sep=" ")},
        "base_load": {"kw": base, "samples": len(night_kw),
                      "method": f"median demand {night[0]}–{night[1]} local"},
        "operating_hours": {"spec": operating_hours or DEFAULT_OPERATING_HOURS,
                            "holidays": sorted(d.isoformat() for d in closed)},
        "out_of_hours": {
            "kwh": round(ooh_kwh, 3),
            "share_pct": round(100.0 * ooh_kwh / total, 2) if total > 0 else None,
            "above_base_load_kwh": above, "note": OPPORTUNITY_NOTE,
        },
        "load_factor": round(mean_kw / peak_kw, 4) if peak_kw > 0 else None,
        "day_types": _day_types(daily),
        "daily": daily,
        "heatmap": _heatmap(locals_kw),
    }  # fmt: skip
    return {**result, "findings": findings(result), "warnings": warnings(result)}


def profile_by_meter(intervals: Sequence[Interval], *, meter: str = "", **options) -> dict:
    """Profile every meter in ``intervals`` (or just ``meter``)."""
    grouped: dict[str, list[Interval]] = defaultdict(list)
    for iv in intervals:
        grouped[iv.meter].append(iv)
    if meter:
        if meter not in grouped:
            raise ValueError(f"meter {meter!r} not in the file (has: {', '.join(sorted(grouped))})")
        grouped = {meter: grouped[meter]}
    if not grouped:
        raise ValueError("no half-hour intervals to analyse")
    profiles = {m: analyse_load_profile(ivs, **options) for m, ivs in sorted(grouped.items())}
    return {"meters": sorted(profiles), "profiles": profiles}


__all__ = [
    "DEFAULT_OPERATING_HOURS",
    "OPPORTUNITY_NOTE",
    "analyse_load_profile",
    "parse_days",
    "parse_operating_hours",
    "profile_by_meter",
    "resolve_window",
]
