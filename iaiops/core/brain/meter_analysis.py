"""One engine for both front-ends: supplier HH text in, per-meter profile (+ cost) out.

The CLI (``iaiops meter``) and the MCP tools (``meter_hh_check`` /
``meter_load_profile``) are thin callers of these two functions, so the agent and
the command line cannot disagree about what a file says.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval, ParseResult, parse_hh_csv
from iaiops.core.brain.load_profile import DEFAULT_OPERATING_HOURS, analyse_load_profile
from iaiops.core.brain.tariff import cost_intervals, load_tariff

_SERIES_KEYS = ("daily", "heatmap")


def _local(instant: datetime) -> str:
    return uk_clock.to_local(instant).isoformat(sep=" ")[:16]


def _summary(parsed: ParseResult) -> dict:
    by_meter: dict[str, list[Interval]] = defaultdict(list)
    for iv in parsed.intervals:
        by_meter[iv.meter].append(iv)
    meters = [
        {"meter": m, "intervals": len(ivs), "first_local": _local(ivs[0].start_utc),
         "last_local": _local(ivs[-1].start_utc)}
        for m, ivs in sorted(by_meter.items())
    ]  # fmt: skip
    return {
        "layout": parsed.layout,
        "unit": parsed.unit,
        "meters": meters,
        "counts": dict(parsed.counts),
        "assumptions": list(parsed.assumptions),
        "warnings": list(parsed.warnings),
    }


def parse_summary(text: str, *, unit: str = "auto", timestamp_marks: str = "start") -> dict:
    """What the file contains, before any analysis: layout, meters, span, rejects."""
    return _summary(parse_hh_csv(text, unit=unit, timestamp_marks=timestamp_marks))


def analyse_hh(
    text: str,
    *,
    meter: str = "",
    operating_hours: str = DEFAULT_OPERATING_HOURS,
    holidays: Iterable[str] = (),
    since: str | None = None,
    until: str | None = None,
    tariff: Mapping | None = None,
    unit: str = "auto",
    timestamp_marks: str = "start",
    include_series: bool = True,
) -> dict:
    """Parse, then profile (and price, when a tariff is given) each meter."""
    parsed = parse_hh_csv(text, unit=unit, timestamp_marks=timestamp_marks)
    loaded = load_tariff(tariff) if tariff else None
    days = tuple(holidays)
    grouped: dict[str, list[Interval]] = defaultdict(list)
    for iv in parsed.intervals:
        grouped[iv.meter].append(iv)
    if meter and meter not in grouped:
        raise ValueError(f"meter {meter!r} not in the file (has: {', '.join(sorted(grouped))})")
    if not grouped:
        raise ValueError("the file contains no usable half-hour readings")
    chosen = {meter: grouped[meter]} if meter else dict(grouped)
    profiles = {}
    for name, intervals in sorted(chosen.items()):
        profile = analyse_load_profile(
            intervals, operating_hours=operating_hours, holidays=days, since=since, until=until
        )
        if not include_series:
            profile = {k: v for k, v in profile.items() if k not in _SERIES_KEYS}
        cost = (
            cost_intervals(intervals, loaded, holidays=days, since=since, until=until)
            if loaded
            else None
        )
        profiles[name] = {"profile": profile, "cost": cost}
    return {"parse": _summary(parsed), "profiles": profiles}


__all__ = ["analyse_hh", "parse_summary"]
