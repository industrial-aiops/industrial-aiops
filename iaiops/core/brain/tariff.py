"""Price half-hourly consumption against a time-of-use tariff.

A tariff is a list of unit-rate bands (p/kWh), each applying on some days between
two local clock times, plus a daily standing charge. Bands are matched **in the
order listed — first match wins**, so a short peak band ("red", weekdays
16:00–19:00) goes above the day band it sits inside. Every half hour of every day
must be priced by some band; a gap is refused with the slot named, because an
unpriced half hour would silently cost nothing.

Deliberately NOT built in:

* **DNO DUoS red/amber/green times.** They differ by distribution region and
  change with each charging statement (待核实 per site). A built-in table would be
  wrong for most readers and look authoritative to all of them. An example tariff
  ships as data, not as a default.
* **VAT, Climate Change Levy, capacity (kVA) and reactive-power charges.** They
  are listed in ``excluded`` on every result so a total is never read as a bill.

Bank holidays are priced as Sunday when passed in ``holidays``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from iaiops.core.brain import uk_clock
from iaiops.core.brain.hh_import import Interval
from iaiops.core.brain.load_profile import parse_days, resolve_window

_ALL_DAYS = frozenset(range(7))
_NAMED_DAYS = {"all": _ALL_DAYS, "weekdays": frozenset(range(5)), "weekends": frozenset({5, 6})}
_HOLIDAY_WEEKDAY = 6  # priced as Sunday
MAX_BANDS = 48
EXCLUDED = (
    "VAT",
    "Climate Change Levy",
    "capacity / availability (kVA) charges",
    "reactive power charges",
    "any separately itemised DUoS / TNUoS / metering charges",
)


@dataclass(frozen=True)
class Band:
    name: str
    rate_p_per_kwh: float
    days: frozenset[int]
    start_min: int
    end_min: int

    def covers(self, weekday: int, minute: int) -> bool:
        if weekday not in self.days:
            return False
        if self.start_min < self.end_min:
            return self.start_min <= minute < self.end_min
        return minute >= self.start_min or minute < self.end_min  # wraps midnight


@dataclass(frozen=True)
class Tariff:
    name: str
    bands: tuple[Band, ...]
    standing_charge_p_per_day: float


def _rate(value, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number, got {value!r}") from exc
    if not math.isfinite(out) or out < 0:
        raise ValueError(f"{label} must be a finite number ≥ 0, got {value!r}")
    return out


def _clock(value, label: str) -> int:
    text = str(value).strip()
    try:
        hour, minute = (int(x) for x in text.split(":"))
    except ValueError as exc:
        raise ValueError(f"{label} must be HH:MM, got {value!r}") from exc
    total = hour * 60 + minute
    if not 0 <= total <= 1440 or minute not in (0, 30):
        raise ValueError(f"{label} must be on the half-hour grid (HH:00 / HH:30), got {value!r}")
    return total


def _band_days(value, label: str) -> frozenset[int]:
    if isinstance(value, str) and value.strip().lower() in _NAMED_DAYS:
        return _NAMED_DAYS[value.strip().lower()]
    tokens = [value] if isinstance(value, str) else list(value or [])
    days: set[int] = set()
    for token in tokens:
        try:
            days.update(parse_days(str(token).strip().lower()))
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from exc
    if not days:
        raise ValueError(f"{label} names no days")
    return frozenset(days)


def _band(raw: Mapping, index: int) -> Band:
    label = f"unit_rates[{index}]"
    name = str(raw.get("name") or f"band {index + 1}")[:40]
    start = _clock(raw.get("start", ""), f"{label}.start")
    end = _clock(raw.get("end", ""), f"{label}.end")
    if start == 1440:
        raise ValueError(f"{label}.start may not be 24:00")
    if start == end % 1440 and not (start == 0 and end == 1440):
        raise ValueError(f"{label} starts and ends at the same time")
    rate = _rate(raw.get("rate"), f"{label}.rate")
    return Band(name, rate, _band_days(raw.get("days", "all"), f"{label}.days"), start, end)


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _run_text(start: int, end: int) -> str:
    return "all day" if (start, end) == (0, 1440) else f"{_hhmm(start)}–{_hhmm(end % 1440)}"


def _gap_runs(bands: Sequence[Band], weekday: int) -> tuple[tuple[int, int], ...]:
    """Contiguous unpriced runs of one day, a run across midnight joined into one."""
    runs: list[tuple[int, int]] = []
    for m in range(0, 1440, 30):
        if any(b.covers(weekday, m) for b in bands):
            continue
        if runs and runs[-1][1] == m:
            runs[-1] = (runs[-1][0], m + 30)
        else:
            runs.append((m, m + 30))
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == 1440:
        runs = [(runs[-1][0], runs[0][1]), *runs[1:-1]]
    return tuple(runs)


def _check_coverage(bands: Sequence[Band]) -> None:
    by_runs: dict[tuple, list[str]] = {}
    for day in range(7):
        runs = _gap_runs(bands, day)
        if runs:
            by_runs.setdefault(runs, []).append(DAY_NAMES[day])
    if by_runs:
        parts = [
            f"{','.join(days)} " + ", ".join(_run_text(a, b) for a, b in runs)
            for runs, days in by_runs.items()
        ]
        raise ValueError("tariff leaves half hours unpriced: " + "; ".join(parts))


DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def load_tariff(spec: Mapping) -> Tariff:
    """Validate a tariff mapping (as loaded from YAML/JSON) into a :class:`Tariff`."""
    if not isinstance(spec, Mapping):
        raise ValueError("tariff must be a mapping with a 'unit_rates' list")
    raw_bands = spec.get("unit_rates")
    if not isinstance(raw_bands, list) or not raw_bands:
        raise ValueError("tariff needs a non-empty 'unit_rates' list")
    if len(raw_bands) > MAX_BANDS:
        raise ValueError(f"too many bands ({len(raw_bands)}; cap {MAX_BANDS})")
    bands = tuple(_band(b if isinstance(b, Mapping) else {}, i) for i, b in enumerate(raw_bands))
    _check_coverage(bands)
    standing = _rate(spec.get("standing_charge_p_per_day", 0), "standing_charge_p_per_day")
    return Tariff(str(spec.get("name") or "tariff")[:80], bands, standing)


def _band_for(tariff: Tariff, local: datetime, holidays: frozenset[date]) -> Band:
    weekday = _HOLIDAY_WEEKDAY if local.date() in holidays else local.weekday()
    minute = local.hour * 60 + local.minute
    return next(b for b in tariff.bands if b.covers(weekday, minute))


def _band_row(name: str, rate: float, kwh: float, total_kwh: float, energy: float) -> dict:
    cost = kwh * rate / 100.0
    return {
        "name": name, "rate_p_per_kwh": rate, "kwh": round(kwh, 3), "cost_gbp": round(cost, 2),
        "share_kwh_pct": round(100.0 * kwh / total_kwh, 2) if total_kwh else None,
        "share_cost_pct": round(100.0 * cost / energy, 2) if energy else None,
    }  # fmt: skip


def _shift_bound(rows: list[dict], bands: Sequence[Band]) -> dict | None:
    rates = {b.rate_p_per_kwh for b in bands}
    if len(rates) < 2:
        return None
    cheapest = min(rates)
    dearest = max(
        (r for r in rows if r["kwh"] > 0), key=lambda r: r["rate_p_per_kwh"], default=None
    )
    if dearest is None or dearest["rate_p_per_kwh"] <= cheapest:
        return None
    gap = dearest["rate_p_per_kwh"] - cheapest
    return {
        "band": dearest["name"], "kwh": dearest["kwh"], "rate_gap_p": round(gap, 4),
        "saving_gbp": round(dearest["kwh"] * gap / 100.0, 2),
        "note": "upper bound: assumes ALL of this band's use could move to the cheapest "
                "rate; in practice only flexible loads can move",
    }  # fmt: skip


def cost_intervals(
    intervals: Sequence[Interval],
    tariff: Tariff,
    *,
    holidays: Iterable[str | date] = (),
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> dict:
    """Cost ONE meter's measured half hours under ``tariff``."""
    ordered = sorted(intervals, key=lambda iv: iv.start_utc)
    if not ordered:
        raise ValueError("no half-hour intervals to price")
    if len({iv.meter for iv in ordered}) > 1:
        raise ValueError("intervals from several meters; price one meter at a time")
    closed = frozenset(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in holidays)
    start, end, _ = resolve_window(ordered, since, until)
    kwh_by_band = {b.name: 0.0 for b in tariff.bands}
    for iv in ordered:
        if start <= iv.start_utc < end:
            band = _band_for(tariff, uk_clock.to_local(iv.start_utc), closed)
            kwh_by_band[band.name] += iv.kwh
    rates = {b.name: b.rate_p_per_kwh for b in reversed(tariff.bands)}  # first listed wins
    total_kwh = sum(kwh_by_band.values())
    energy = sum(kwh * rates[name] / 100.0 for name, kwh in kwh_by_band.items())
    rows = [
        _band_row(name, rates[name], kwh, total_kwh, energy) for name, kwh in kwh_by_band.items()
    ]
    first_day = uk_clock.to_local(start).date()
    last_day = uk_clock.to_local(end - timedelta(microseconds=1)).date()
    days = (last_day - first_day).days + 1
    standing = days * tariff.standing_charge_p_per_day / 100.0
    return {
        "tariff": tariff.name, "currency": "GBP", "bands": rows,
        "measured_kwh": round(total_kwh, 3), "energy_cost_gbp": round(energy, 2),
        "standing": {"days": days, "p_per_day": tariff.standing_charge_p_per_day,
                     "cost_gbp": round(standing, 2)},
        "total_gbp": round(energy + standing, 2),
        "avg_p_per_kwh": round(100.0 * energy / total_kwh, 3) if total_kwh else None,
        "shift_upper_bound": _shift_bound(rows, tariff.bands),
        "coverage_note": "unit costs cover measured half hours only; missing half hours are "
                         "not priced, so a bill for the same period will be higher",
        "excluded": list(EXCLUDED),
    }  # fmt: skip


__all__ = ["EXCLUDED", "Band", "Tariff", "cost_intervals", "load_tariff"]
