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
from iaiops.core.brain.load_profile import (
    DEFAULT_OPERATING_HOURS,
    EmptyWindowError,
    analyse_load_profile,
)
from iaiops.core.brain.tariff import Tariff, cost_intervals, load_tariff

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


def file_warnings(parsed: ParseResult) -> list[str]:
    """What the parser left out, phrased for the reader of a profile.

    Without these, rows the parser refused simply vanish: a profile built from what
    remained reads 100% coverage when the refused rows sat at either end of the
    file, because the data-span window shrinks to fit what is left.
    """
    c = parsed.counts
    out = []
    if c["rows_rejected"]:
        out.append(
            f"{c['rows_rejected']} rows of the file were rejected and are in none of these "
            "figures (run `iaiops meter check` for why). Coverage counts only the period the "
            "remaining rows span — pass since/until to measure the whole period."
        )
    if c["duplicate_conflicting"]:
        out.append(
            f"{c['duplicate_conflicting']} half hours appear twice in the file with different "
            "values; the first was kept."
        )
    if c["negative_rejected"]:
        out.append(f"{c['negative_rejected']} negative values rejected (export or a meter fault).")
    if c["unrecognised_flags"]:
        out.append(
            f"{c['unrecognised_flags']} values carry an unrecognised read-type code and are "
            "counted as estimated."
        )
    return out


def _profile_one(
    intervals: list[Interval], loaded: Tariff | None, notes: list[str], options: dict
) -> dict:
    profile = analyse_load_profile(intervals, **options)
    profile = {**profile, "warnings": notes + profile["warnings"]}
    window = {k: options[k] for k in ("holidays", "since", "until")}
    cost = cost_intervals(intervals, loaded, **window) if loaded else None
    return {"profile": profile, "cost": cost}


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
    """Parse, then profile (and price, when a tariff is given) each meter.

    A meter with no measured half hour inside a requested window is listed in
    ``skipped`` rather than failing the others.
    """
    parsed = parse_hh_csv(text, unit=unit, timestamp_marks=timestamp_marks)
    loaded = load_tariff(tariff) if tariff else None
    grouped: dict[str, list[Interval]] = defaultdict(list)
    for iv in parsed.intervals:
        grouped[iv.meter].append(iv)
    if meter and meter not in grouped:
        raise ValueError(f"meter {meter!r} not in the file (has: {', '.join(sorted(grouped))})")
    if not grouped:
        raise ValueError("the file contains no usable half-hour readings")
    chosen = {meter: grouped[meter]} if meter else dict(grouped)
    options = {"operating_hours": operating_hours, "holidays": tuple(holidays),
               "since": since, "until": until}  # fmt: skip
    notes = file_warnings(parsed)
    profiles, skipped = {}, {}
    for name, intervals in sorted(chosen.items()):
        try:
            entry = _profile_one(intervals, loaded, notes, options)
        except EmptyWindowError as exc:
            skipped[name] = str(exc)
            continue
        if not include_series:
            entry = {**entry, "profile": {k: v for k, v in entry["profile"].items()
                                          if k not in _SERIES_KEYS}}  # fmt: skip
        profiles[name] = entry
    if not profiles:
        raise ValueError("no meter has measured half hours inside the requested window")
    return {"parse": _summary(parsed), "profiles": profiles, "skipped": skipped}


__all__ = ["analyse_hh", "file_warnings", "parse_summary"]
