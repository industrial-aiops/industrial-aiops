"""PID control-loop health — oscillation / offset / saturation triage (pure).

The process-industry loop-tuning question: *is this loop actually controlling?*
From a short PV / SP / OP capture it flags the three classic misbehaviours a
control engineer looks for:

  * **Oscillation** — PV crossing SP repeatedly (too much gain, or valve
    stiction) — measured as the crossing rate of the error signal.
  * **Sustained offset** — PV sitting away from SP (integral windup, undersized
    valve, or a load it can't reach).
  * **Output saturation** — OP pinned at 0 % or 100 % (the loop is out of range;
    the valve is fully shut/open and can do no more).

Pure function over an injected sample series; read-only and advisory, every flag
cited by its number. Not a tuner — it triages which loops need attention.
"""

from __future__ import annotations

from statistics import pstdev

MIN_SAMPLES = 8

# Defaults: OP range, saturation fraction that counts as "pinned", oscillation
# crossing-rate that counts as oscillating, offset band as a fraction of |SP|.
DEFAULT_OP_MIN = 0.0
DEFAULT_OP_MAX = 100.0
DEFAULT_SAT_PCT = 90.0
DEFAULT_OSC_INDEX = 0.3
DEFAULT_OFFSET_FRAC = 0.02


def control_loop_health(
    samples: list[dict],
    offset_band: float | None = None,
    op_min: float = DEFAULT_OP_MIN,
    op_max: float = DEFAULT_OP_MAX,
    sat_pct: float = DEFAULT_SAT_PCT,
    osc_index_max: float = DEFAULT_OSC_INDEX,
) -> dict:
    """[READ] Triage a control loop from a PV/SP/OP sample capture.

    ``samples`` are ``{pv, sp, op}`` (op optional). Returns the mean offset, the
    error-crossing oscillation index, and the fraction of time OP sat at 0/100 %,
    then a ``verdict`` — ``saturated`` > ``oscillating`` > ``offset`` > ``ok``
    (worst wins). ``offset_band`` (PV units) defaults to 2 % of the mean |SP|.
    Refuses fewer than 8 samples. Every flag is cited by its number.
    """
    pv, sp, op = _extract(samples)
    if len(pv) < MIN_SAMPLES or len(pv) != len(sp):
        return {"samples": len(pv), "verdict": "insufficient_data",
                "needed": MIN_SAMPLES, "note": _NOTE}

    errors = [p - s for p, s in zip(pv, sp)]
    mean_offset = sum(errors) / len(errors)
    mean_abs_offset = sum(abs(e) for e in errors) / len(errors)
    crossings = _sign_changes(errors)
    osc_index = round(crossings / (len(errors) - 1), 3) if len(errors) > 1 else 0.0

    band = offset_band if offset_band is not None else _default_band(sp)
    sat_low, sat_high = _saturation(op, op_min, op_max)

    verdict, detail = _verdict(
        mean_offset, band, osc_index, osc_index_max, sat_low, sat_high, sat_pct
    )
    return {
        "samples": len(pv),
        "meanOffset": round(mean_offset, 4),
        "meanAbsOffset": round(mean_abs_offset, 4),
        "offsetBand": round(band, 4),
        "crossings": crossings,
        "oscillationIndex": osc_index,
        "opSaturationLowPct": sat_low,
        "opSaturationHighPct": sat_high,
        "pvStdev": round(pstdev(pv), 4) if len(pv) > 1 else 0.0,
        "verdict": verdict,
        "detail": detail,
        "note": _NOTE,
    }


_NOTE = (
    "Advisory control-loop triage over an injected PV/SP/OP capture; flags are "
    "cited by their numbers. Not a tuner — it says which loops need a look "
    "(oscillating / offset / saturated), not how to retune them."
)


def _extract(samples: list[dict]) -> tuple[list[float], list[float], list[float]]:
    pv: list[float] = []
    sp: list[float] = []
    op: list[float] = []
    for s in samples or []:
        if not isinstance(s, dict):
            continue
        p, sepoint = s.get("pv"), s.get("sp")
        if isinstance(p, (int, float)) and isinstance(sepoint, (int, float)):
            pv.append(float(p))
            sp.append(float(sepoint))
            o = s.get("op")
            op.append(float(o) if isinstance(o, (int, float)) else float("nan"))
    return pv, sp, op


def _sign_changes(errors: list[float]) -> int:
    """Count sign changes of the error signal (crossings of SP by PV)."""
    changes = 0
    prev = 0
    for e in errors:
        sign = 1 if e > 0 else (-1 if e < 0 else 0)
        if sign != 0 and prev != 0 and sign != prev:
            changes += 1
        if sign != 0:
            prev = sign
    return changes


def _default_band(sp: list[float]) -> float:
    mag = sum(abs(s) for s in sp) / len(sp) if sp else 0.0
    return max(1e-9, DEFAULT_OFFSET_FRAC * mag)


def _saturation(op: list[float], op_min: float, op_max: float) -> tuple[float, float]:
    valid = [o for o in op if o == o]  # drop NaN (missing OP)
    if not valid:
        return 0.0, 0.0
    eps = 1e-6
    low = sum(1 for o in valid if o <= op_min + eps) / len(valid) * 100.0
    high = sum(1 for o in valid if o >= op_max - eps) / len(valid) * 100.0
    return round(low, 1), round(high, 1)


def _verdict(
    mean_offset: float, band: float, osc_index: float, osc_max: float,
    sat_low: float, sat_high: float, sat_pct: float,
) -> tuple[str, str]:
    if sat_high >= sat_pct:
        return "saturated", f"OP pinned high {sat_high}% of the time — loop out of range"
    if sat_low >= sat_pct:
        return "saturated", f"OP pinned low {sat_low}% of the time — loop out of range"
    if osc_index > osc_max:
        return "oscillating", f"error crosses SP at index {osc_index} (> {osc_max})"
    if abs(mean_offset) > band:
        return "offset", f"mean offset {round(mean_offset, 4)} exceeds band ±{round(band, 4)}"
    return "ok", "PV tracks SP within band; OP not saturated"


__all__ = ["control_loop_health", "MIN_SAMPLES"]
