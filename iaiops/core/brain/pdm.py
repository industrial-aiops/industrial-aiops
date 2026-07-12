"""Predictive maintenance — trend + time-to-threshold forecasting (READ-ONLY, pure).

The baseline module flags a *violation that has already happened*; this is the predictive step:
from a value's recent history it estimates the **trend direction** and, if the trend continues, the
**time until it crosses a warn/alarm limit** — the early warning that turns preventive maintenance
into predictive maintenance (inverter/turbine degradation, bearing drift, filter clogging, …).

Deliberately NOT a black box: the slope is a robust **Theil–Sen** estimator (median of pairwise
slopes — no ML, resistant to outliers/spikes), it **refuses thin history** (like baseline learning),
and every verdict cites its window, slope, current value, limit, and ETA. Pure/injectable: analyzes
PROVIDED series, so it is fully unit-testable without a live plant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median
from typing import Any

from iaiops.core.brain._shared import num, s

MAX_POINTS = 5_000
MIN_SAMPLES = 30          # below this, refuse (insufficient_data) rather than extrapolate noise
_FLAT_EPS = 1e-9          # |slope| below this is treated as flat


def _parse_ts(ts: Any) -> float | None:
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _extract(series: list[Any]) -> tuple[list[float], list[float | None]]:
    """Return (values, times) — times are epoch seconds or None (fall back to sample index)."""
    values: list[float] = []
    times: list[float | None] = []
    for item in list(series or [])[:MAX_POINTS]:
        if isinstance(item, dict):
            v = num(item.get("value"))
            t = _parse_ts(item.get("timestamp") or item.get("ts") or item.get("recorded_at"))
        else:
            v = num(item)
            t = None
        if v is None:
            continue
        values.append(v)
        times.append(t)
    return values, times


def _theil_sen(xs: list[float], ys: list[float]) -> float:
    """Median of pairwise slopes (robust to outliers). O(n²); n is bounded by MAX_POINTS."""
    slopes: list[float] = []
    n = len(xs)
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if dx != 0:
                slopes.append((ys[j] - ys[i]) / dx)
    return median(slopes) if slopes else 0.0


def _nearest_limit(
    current: float, slope: float, limits: dict[str, float | None]
) -> tuple[str, float] | None:
    """Pick the limit the value is heading TOWARD given the slope sign (warn before alarm)."""
    candidates: list[tuple[str, float]] = []
    if slope > 0:  # rising → high limits ahead of current
        for name in ("warn_high", "alarm_high"):
            lim = limits.get(name)
            if lim is not None and lim > current:
                candidates.append((name, lim))
    elif slope < 0:  # falling → low limits below current
        for name in ("warn_low", "alarm_low"):
            lim = limits.get(name)
            if lim is not None and lim < current:
                candidates.append((name, lim))
    if not candidates:
        return None
    # nearest first (smallest distance) — warn is usually crossed before alarm
    return min(candidates, key=lambda c: abs(c[1] - current))


def pdm_forecast(
    series: list[Any],
    warn_high: float | None = None,
    alarm_high: float | None = None,
    warn_low: float | None = None,
    alarm_low: float | None = None,
    imminent_within_s: float = 86_400.0,
    min_samples: int = MIN_SAMPLES,
) -> dict:
    """Estimate a value's trend and the time until it crosses a warn/alarm limit.

    Returns ``{status, ...}`` where status is ``insufficient_data`` (too few samples), ``stable``
    (flat trend), ``degrading`` (heading toward a limit with an ETA), or ``imminent`` (ETA within
    ``imminent_within_s``). ETA is in seconds when the series carries timestamps, else in samples.
    """
    values, times = _extract(series)
    n = len(values)
    if n < int(min_samples):
        return {
            "status": "insufficient_data",
            "samples": n,
            "needed": int(min_samples),
            "note": f"Need >= {int(min_samples)} numeric samples to forecast (got {n}).",
        }
    have_time = all(t is not None for t in times)
    xs = [float(t) for t in times] if have_time else [float(i) for i in range(n)]  # type: ignore[arg-type]
    slope = _theil_sen(xs, values)
    current = values[-1]
    unit = "s" if have_time else "samples"

    if abs(slope) < _FLAT_EPS:
        return _result("stable", n, slope, current, unit, None, None, None)

    limits = {"warn_high": warn_high, "alarm_high": alarm_high,
              "warn_low": warn_low, "alarm_low": alarm_low}
    target = _nearest_limit(current, slope, limits)
    if target is None:
        return _result("stable", n, slope, current, unit, None, None, None,
                       note="Trending but no limit configured in the direction of travel.")
    limit_name, limit_val = target
    eta = (limit_val - current) / slope  # slope sign matches direction → eta > 0
    status = "imminent" if (have_time and 0 <= eta <= float(imminent_within_s)) else "degrading"
    return _result(status, n, slope, current, unit, limit_name, limit_val, eta)


def _result(status, n, slope, current, unit, limit_name, limit_val, eta, note=None) -> dict:
    out = {
        "status": status,
        "samples": n,
        "direction": ("rising" if slope > _FLAT_EPS
                      else "falling" if slope < -_FLAT_EPS else "flat"),
        "slope_per_unit": round(slope, 9),
        "unit": unit,
        "current": round(current, 6),
        "limit": limit_name and {"name": s(limit_name, 20), "value": limit_val},
        "eta_to_limit": None if eta is None else round(eta, 2),
    }
    if note:
        out["note"] = note
    return out


__all__ = ["pdm_forecast", "MIN_SAMPLES", "MAX_POINTS"]
